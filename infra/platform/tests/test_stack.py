import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('nexus_stack', Path(__file__).resolve().parents[1] / 'stack.py')
stack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stack)


class StackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'state'
        self.args = argparse.Namespace(project_name='nexus-test', domain='lab.home.arpa', admin_email='admin@example.test')
        stack.initialize(self.args, self.root)
        self.values = stack.config(self.root)

    def test_initialization_is_private_and_immutable(self):
        """Repeated init cannot lose the encryption, database or recovery secrets."""
        before = (self.root / '.env').read_bytes()
        self.assertEqual((self.root / '.env').stat().st_mode & 0o777, 0o600)
        self.assertEqual(len({self.values[key] for key in stack.SECRET_KEYS}), len(stack.SECRET_KEYS))
        with self.assertRaises(ValueError):
            stack.initialize(self.args, self.root)
        self.assertEqual(before, (self.root / '.env').read_bytes())

    def test_public_bind_and_injected_domain_are_rejected(self):
        """Configuration typos cannot publish a first-user setup page to all interfaces."""
        (self.root / 'bootstrap-reviewed.json').write_text('{}')
        for ip in ('0.0.0.0', '192.168.1.20', '8.8.8.8'):
            with self.subTest(ip=ip), self.assertRaises(ValueError):
                stack.validate_values(self.values | {'BIND_IP': ip}, self.root)
        for domain in ('lab.home.arpa\nmalicious: value', 'x/../../etc', 'https://lab.home.arpa', '-bad.home.arpa'):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                stack.validate_values(self.values | {'LAB_DOMAIN': domain}, self.root)

    def test_tailnet_publication_requires_bootstrap_assertion(self):
        """Even an allowed private address cannot expose the uninitialized dashboards."""
        with self.assertRaises(ValueError):
            stack.validate_values(self.values | {'BIND_IP': '100.100.1.2'}, self.root)

    def test_real_compose_limits_host_access_and_preserves_state(self):
        """Inspect Compose's resolved model, including optional research and tool services."""
        rendered = stack.compose(self.root, self.values, '--profile', 'research', '--profile', 'tools', '--profile', 'memory',
                                 'config', '--format', 'json', capture_output=True, text=True)
        model = json.loads(rendered.stdout)
        services = model['services']
        for name, service in services.items():
            if name == 'caddy':
                self.assertEqual({p['host_ip'] for p in service['ports']}, {'127.0.0.1'})
            else:
                self.assertNotIn('ports', service, name)
            for volume in service.get('volumes', []):
                self.assertNotIn('docker.sock', volume['source'])
        self.assertEqual(services['memory']['command'][-1], 'stdio')
        self.assertEqual(services['snapshot']['network_mode'], 'none')
        self.assertIn('nexus-test-ai', {n['name'] for n in model['networks'].values()})
        self.assertEqual(services['homarr']['environment']['AUTH_PROVIDERS'], 'credentials')

    def test_ambient_environment_cannot_change_secrets_or_profiles(self):
        """A shell export cannot enable services or replace persistent credentials."""
        with patch.dict(os.environ, {'AUTH_DB_PASSWORD': 'unexpected', 'COMPOSE_PROFILES': 'memory'}):
            model = json.loads(stack.compose(self.root, self.values, 'config', '--format', 'json',
                                            capture_output=True, text=True).stdout)
        self.assertEqual(model['services']['auth-db']['environment']['POSTGRES_PASSWORD'], self.values['AUTH_DB_PASSWORD'])
        self.assertNotIn('memory', model['services'])

    def test_templates_have_no_embedded_oidc_secrets(self):
        """Generated blueprints may be inspected without disclosing client credentials."""
        blueprint = (self.root / 'config/blueprints/nexus.yaml').read_text()
        self.assertNotIn('@@', blueprint)
        for key in stack.SECRET_KEYS:
            self.assertNotIn(self.values[key], blueprint)
        self.assertIn('email_verified", False', blueprint)
        self.assertIn('/api/auth/oidc/callback', blueprint)
        self.assertIn('/api/oauth2-redirect', blueprint)

    def test_generated_configs_are_readable_inside_nonroot_containers(self):
        """Bind mounts must be traversable without opening the private host state directory."""
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        for path in (self.root / 'config').rglob('*'):
            self.assertTrue(path.stat().st_mode & 0o004, path)
            if path.is_dir():
                self.assertTrue(path.stat().st_mode & 0o001, path)

    def test_restic_refuses_missing_nas_before_docker(self):
        """An absent NAS must not fill the local NVMe with repository writes."""
        args = argparse.Namespace(nas_mount=Path(self.temp.name), repository=Path(self.temp.name) / 'repo', source=self.root)
        with patch.object(stack.subprocess, 'run') as run, self.assertRaises(ValueError):
            stack.restic(self.root, self.values, args, 'backup', '/snapshot')
        run.assert_not_called()

    def test_memory_session_blocks_inconsistent_backup(self):
        """An active MCP SQLite writer must not be silently archived."""
        with patch.object(stack.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='active-container')):
            with self.assertRaises(ValueError):
                stack.backup(self.root, self.values, Path(self.temp.name) / 'backup')


class RecoveryTests(unittest.TestCase):
    def make_backup(self, root, member='homarr-data/settings.json', link=False):
        (root / 'database.dump').write_bytes(b'database dump')
        for name in ('volumes.tar.gz', 'configuration.tar.gz'):
            with tarfile.open(root / name, 'w:gz') as archive:
                item = tarfile.TarInfo(member if name == 'volumes.tar.gz' else '.env')
                data = b'state'
                item.size = len(data)
                if link:
                    item.type = tarfile.SYMTYPE
                    item.linkname = '/etc/passwd'
                archive.addfile(item, io.BytesIO(data))
        manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
        (root / 'checksums.json').write_text(json.dumps(manifest))

    def test_integrity_verifier_accepts_valid_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_backup(root)
            stack.verify_backup(root)

    def test_corrupt_or_path_escaping_archive_is_rejected(self):
        for member in ('../../etc/passwd', '/etc/passwd', 'unknown-volume/state'):
            with self.subTest(member=member), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_backup(root, member)
                with self.assertRaises(ValueError):
                    stack.verify_backup(root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_backup(root)
            (root / 'database.dump').write_bytes(b'corrupt')
            with self.assertRaises(ValueError):
                stack.verify_backup(root)

    def test_symlink_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_backup(root, link=True)
            with self.assertRaises(ValueError):
                stack.verify_backup(root)

    def test_only_upstream_media_link_is_accepted_without_traversal(self):
        """Authentik's exact compatibility link is valid, but no payload may follow it."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_backup(root)
            def replace_archive(child=None):
                with tarfile.open(root / 'volumes.tar.gz', 'w:gz') as archive:
                    link = tarfile.TarInfo('auth-data/media')
                    link.type = tarfile.SYMTYPE
                    link.linkname = '/media'
                    archive.addfile(link)
                    if child:
                        item = tarfile.TarInfo(child)
                        item.size = 1
                        archive.addfile(item, io.BytesIO(b'x'))
                manifest = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                            for name in ('database.dump', 'volumes.tar.gz', 'configuration.tar.gz')}
                (root / 'checksums.json').write_text(json.dumps(manifest))
            replace_archive()
            stack.verify_backup(root)
            for child in ('auth-data/media/escape', 'auth-data//media/escape', 'auth-data/./media/escape'):
                replace_archive(child)
                with self.subTest(child=child), self.assertRaises(ValueError):
                    stack.verify_backup(root)

    def test_restore_refuses_existing_destination_before_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'backup'
            source.mkdir()
            self.make_backup(source)
            target = Path(directory) / 'existing'
            target.mkdir()
            (target / 'keep').write_text('important')
            args = argparse.Namespace(backup=source, project_name='recovery')
            with patch.object(stack.subprocess, 'run') as run, self.assertRaises(ValueError):
                stack.restore(target, args)
            run.assert_not_called()
            self.assertEqual((target / 'keep').read_text(), 'important')


if __name__ == '__main__':
    unittest.main()
