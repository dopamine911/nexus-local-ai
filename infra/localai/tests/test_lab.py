"""Lifecycle safety tests; Compose integration renders configuration without a daemon."""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('lab', PACKAGE / 'lab.py')
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'controller'
        with patch('builtins.print'):
            lab.initialize(argparse.Namespace(admin_email='admin@example.invalid', project_name='test-localai'), self.root)

    def publish(self):
        values = lab.configuration(self.root)
        (self.root / 'admin-bootstrap.json').write_text('{"email":"admin@example.invalid"}')
        values['CONTROLLER_BIND_IP'] = '100.100.1.2'
        lab.write_env(self.root / '.env', values)
        return lab.configuration(self.root)

    def test_reinitialization_preserves_all_credentials(self):
        """A second init must fail rather than invalidate stored API-key hashes."""
        before = (self.root / '.env').read_bytes()
        with self.assertRaisesRegex(ValueError, 'Configuration exists'):
            lab.initialize(argparse.Namespace(admin_email='other@example.invalid', project_name='other'), self.root)
        self.assertEqual(before, (self.root / '.env').read_bytes())

    def test_initial_secrets_are_private_and_distinct(self):
        """Initialization must not use one shared credential for every service."""
        values = lab.configuration(self.root)
        self.assertEqual(4, len(set(values[k] for k in lab.SECRET_KEYS)))
        self.assertEqual(0o600, (self.root / '.env').stat().st_mode & 0o777)
        self.assertEqual('127.0.0.1', values['CONTROLLER_BIND_IP'])

    def test_missing_credentials_do_not_allow_reinitializing_existing_state(self):
        """Losing dotenv must not replace the HMAC secret for an existing database."""
        (self.root / '.env').unlink()
        with self.assertRaisesRegex(ValueError, 'recover the existing credentials'):
            lab.initialize(argparse.Namespace(admin_email='admin@example.invalid', project_name='test-localai'), self.root)
        self.assertFalse((self.root / '.env').exists())

    def test_bootstrap_does_not_mark_nonadmin_account_as_ready(self):
        """An unexpected registration/login response must not unlock public startup."""
        class Response(io.BytesIO):
            pass
        opener = unittest.mock.Mock()
        opener.open.side_effect = [Response(b'{"user":{"role":"user"}}'),
                                   Response(b'{"user":{"role":"user"}}')]
        with patch('getpass.getpass', return_value='long-test-password'), patch('urllib.request.build_opener', return_value=opener):
            with self.assertRaisesRegex(ValueError, 'Could not verify'):
                lab.bootstrap(self.root, lab.configuration(self.root))
        self.assertFalse((self.root / 'admin-bootstrap.json').exists())

    def test_bootstrap_marks_verified_admin_without_saving_password(self):
        """Only a verified administrator response can create the publication marker."""
        opener = unittest.mock.Mock()
        opener.open.return_value = io.BytesIO(b'{"user":{"role":"admin"}}')
        with patch('getpass.getpass', return_value='long-test-password'), patch('urllib.request.build_opener', return_value=opener), patch('builtins.print'):
            lab.bootstrap(self.root, lab.configuration(self.root))
        self.assertEqual({'email': 'admin@example.invalid'}, json.loads((self.root / 'admin-bootstrap.json').read_text()))
        self.assertNotIn('long-test-password', (self.root / '.env').read_text())

    def test_non_loopback_start_requires_bootstrap(self):
        """Editing the binding must not accidentally expose first-user admin creation."""
        values = lab.configuration(self.root)
        values['CONTROLLER_BIND_IP'] = '100.100.1.2'
        lab.write_env(self.root / '.env', values)
        with self.assertRaisesRegex(ValueError, 'Bootstrap'):
            lab.configuration(self.root)

    def test_public_or_wildcard_bindings_are_rejected(self):
        """A typo must not publish plaintext control-plane ports on every interface."""
        for address in ['0.0.0.0', '192.168.1.10', '8.8.8.8', '::1']:
            with self.subTest(address=address), self.assertRaises(ValueError):
                lab.private_ip(address, loopback=True)

    def test_worker_export_omits_controller_secrets(self):
        """Compromising worker enrollment credentials must not reveal DB/HMAC secrets."""
        values = self.publish()
        destination = Path(self.temporary.name) / 'worker.env'
        with patch('builtins.print'):
            lab.export_worker(argparse.Namespace(worker_ip='100.100.1.3', name='m5', output=destination), self.root, values)
        worker = lab.load_config(destination)
        self.assertNotIn('POSTGRES_PASSWORD', worker)
        self.assertNotIn('AUTH_HMAC_SECRET', worker)
        self.assertEqual(values['REGISTRATION_TOKEN'], worker['REGISTRATION_TOKEN'])
        self.assertEqual('m5', worker['NODE_NAME'])

    def test_environment_cannot_override_stack_credentials(self):
        """Ambient shell variables must not replace a saved password during deployment."""
        values = lab.configuration(self.root)
        with patch.dict(os.environ, {'POSTGRES_PASSWORD': 'wrong'}), patch('subprocess.run') as run:
            lab.compose(self.root, values, 'config', '--quiet')
        self.assertNotIn('POSTGRES_PASSWORD', run.call_args.kwargs['env'])
        self.assertIn(str(self.root / '.env'), run.call_args.args[0])

    def test_overly_readable_secret_file_is_rejected(self):
        """An accidental chmod must not leave deployment credentials world readable."""
        (self.root / '.env').chmod(0o644)
        with self.assertRaisesRegex(ValueError, '600'):
            lab.configuration(self.root)

    def test_restore_refuses_nonempty_target_before_docker(self):
        """Recovery must never replace an existing installation's secrets/state."""
        with patch.object(lab, 'verify_backup'), patch('subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'new empty'):
                lab.restore(argparse.Namespace(backup=Path(self.temporary.name), project_name='recovery'), self.root)
        run.assert_not_called()

    @unittest.skipUnless(shutil.which('docker'), 'Docker Compose CLI not installed')
    def test_controller_compose_has_no_public_database_or_monitoring(self):
        """Actual Compose interpolation must preserve private host ports and persistent state."""
        values = lab.configuration(self.root)
        rendered = lab.compose(self.root, values, 'config', '--format', 'json', capture_output=True, text=True)
        config = json.loads(rendered.stdout)
        self.assertNotIn('ports', config['services']['postgres'])
        self.assertEqual([('127.0.0.1', '18080')], [(p['host_ip'], p['published']) for p in config['services']['controller']['ports']])
        self.assertEqual([4222], [p['target'] for p in config['services']['nats']['ports']])
        env = config['services']['controller']['environment']
        self.assertEqual('invite', env['LOCALAI_REGISTRATION_MODE'])
        self.assertEqual(values['AUTH_HMAC_SECRET'], env['LOCALAI_AUTH_HMAC_SECRET'])
        self.assertNotIn('LOCALAI_ADMIN_EMAIL', env)
        self.assertEqual('false', env['LOCALAI_AUTO_APPROVE_NODES'])
        targets = {v['target'] for v in config['services']['controller']['volumes']}
        self.assertTrue({'/data', '/configuration', '/models', '/backends'} <= targets)

    @unittest.skipUnless(shutil.which('docker'), 'Docker Compose CLI not installed')
    def test_worker_compose_advertises_the_host_not_container_localhost(self):
        """The controller must be able to reach staged models and dynamic gRPC ports."""
        source = self.publish()
        worker = Path(self.temporary.name) / 'worker'
        lab.prepare(worker, 'worker')
        values = dict(ROLE='worker', PROJECT_NAME='test-m5', STATE_ROOT=str(worker),
                      WORKER_IMAGE=source['WORKER_IMAGE'], CONTROLLER_IP='100.100.1.2',
                      WORKER_BIND_IP='100.100.1.3', NODE_NAME='m5', NATS_PASSWORD=source['NATS_PASSWORD'],
                      REGISTRATION_TOKEN=source['REGISTRATION_TOKEN'], VIDEO_GID='44', RENDER_GID='109')
        lab.write_env(worker / '.env', values)
        rendered = lab.compose(worker, lab.configuration(worker), 'config', '--format', 'json', capture_output=True, text=True)
        service = json.loads(rendered.stdout)['services']['worker']
        self.assertTrue(all(p['host_ip'] == '100.100.1.3' for p in service['ports']))
        self.assertEqual('100.100.1.3:50051', service['environment']['LOCALAI_ADVERTISE_ADDR'])
        self.assertEqual('http://100.100.1.2:18080', service['environment']['LOCALAI_REGISTER_TO'])
        self.assertEqual('50100', service['environment']['LOCALAI_GRPC_MAX_PORT'])


class BackupTests(unittest.TestCase):
    def make_backup(self, directory, unsafe=False):
        for filename in ('data.tar.gz', 'configuration.tar.gz', 'models-config.tar.gz'):
            with tarfile.open(directory / filename, 'w:gz') as archive:
                item = tarfile.TarInfo('../escape' if unsafe else 'settings.json')
                content = b'{}'
                item.size = len(content)
                archive.addfile(item, io.BytesIO(content))
        for filename in ('database.dump', 'controller.env', 'admin-bootstrap.json'):
            (directory / filename).write_bytes(b'fixture')
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir()}
        (directory / 'checksums.json').write_text(json.dumps(hashes))

    def test_intact_backup_is_accepted(self):
        """The verifier must accept all required uncorrupted archive and state files."""
        with tempfile.TemporaryDirectory() as temporary:
            self.make_backup(Path(temporary))
            lab.verify_backup(Path(temporary))

    def test_corrupt_database_dump_blocks_recovery(self):
        """A damaged dump must fail before any recovery database is started."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.make_backup(directory)
            (directory / 'database.dump').write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'checksum failed: database.dump'):
                lab.verify_backup(directory)

    def test_archive_path_escape_blocks_recovery(self):
        """Even a checksummed archive cannot write outside its restored state directory."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.make_backup(directory, unsafe=True)
            with self.assertRaisesRegex(ValueError, 'Unsafe archive entry'):
                lab.verify_backup(directory)


if __name__ == '__main__':
    unittest.main()
