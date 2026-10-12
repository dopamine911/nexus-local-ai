#!/usr/bin/env python3
"""LocalAI pilot lifecycle. Python stdlib + Docker Compose; no shell eval."""

import argparse
import getpass
import grp
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
import urllib.error
import urllib.request

PACKAGE = Path(__file__).resolve().parent
TAILNET = ipaddress.ip_network('100.64.0.0/10')
SECRET_KEYS = ('POSTGRES_PASSWORD', 'NATS_PASSWORD', 'REGISTRATION_TOKEN', 'AUTH_HMAC_SECRET')


def fail(message):
    raise ValueError(message)


def read_env(path):
    result = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if not sep or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            fail(f'Invalid configuration line in {path.name}')
        if key in result:
            fail(f'Duplicate setting: {key}')
        result[key] = value
    return result


def write_env(path, values):
    for key, value in values.items():
        if any(c in str(value) for c in '\r\n\x00'):
            fail(f'Multiline setting is not supported: {key}')
    temporary = path.with_suffix('.tmp')
    with open(temporary, 'w', opener=lambda p, f: os.open(p, f, 0o600)) as output:
        for key, value in values.items():
            # Single quotes keep Compose from interpolating dollar signs.
            output.write(f"{key}='{str(value).replace(chr(39), chr(92) + chr(39))}'\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def load_config(path):
    values = read_env(path)
    # Generated dotenv values are single-quoted, with escaped literal quotes.
    return {k: v[1:-1].replace("\\'", "'") if v.startswith("'") and v.endswith("'") else v
            for k, v in values.items()}


def private_ip(value, loopback=False):
    address = ipaddress.ip_address(value)
    if address.version != 4 or not (address in TAILNET or (loopback and address.is_loopback)):
        fail('Use an explicit Tailscale IPv4 address; controller bootstrap may use loopback')
    return str(address)


def prepare(root, role):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    for folder in ('models', 'data', 'backends', 'configuration', 'staging', 'cache'):
        (root / folder).mkdir(exist_ok=True, mode=0o700)
    if role == 'controller':
        shutil.copyfile(PACKAGE / 'config/scheduling.yaml', root / 'configuration/scheduling.yaml')


def initialize(args, root):
    path = root / '.env'
    if path.exists():
        fail('Configuration exists; initialization will not rotate credentials or overwrite it')
    if root.exists() and any(root.iterdir()):
        fail('State directory is not empty; recover the existing credentials instead of reinitializing')
    prepare(root, 'controller')
    values = read_env(PACKAGE / 'images.env')
    values.update(ROLE='controller', PROJECT_NAME=args.project_name, STATE_ROOT=str(root),
                  CONTROLLER_BIND_IP='127.0.0.1', ADMIN_EMAIL=args.admin_email,
                  LOCALAI_BASE_URL='', OIDC_ISSUER='', OIDC_CLIENT_ID='', OIDC_CLIENT_SECRET='',
                  DISABLE_LOCAL_AUTH='false')
    values.update({key: secrets.token_hex(32) for key in SECRET_KEYS})
    write_env(path, values)
    print(f'Initialized controller configuration in {root}; credentials were not printed.')


def configuration(root):
    path = root / '.env'
    if path.stat().st_mode & 0o077:
        fail('Set configuration file permissions to 600 before continuing')
    values = load_config(path)
    if values.get('STATE_ROOT') != str(root):
        fail('STATE_ROOT must match --state-dir; use init-worker to prepare a worker on its host')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', values.get('PROJECT_NAME', '')):
        fail('PROJECT_NAME must use lowercase letters, numbers, hyphens or underscores')
    role = values.get('ROLE')
    if role not in ('controller', 'worker'):
        fail('Invalid deployment role')
    private_ip(values.get('CONTROLLER_BIND_IP' if role == 'controller' else 'WORKER_BIND_IP', ''),
               loopback=role == 'controller')
    for key in SECRET_KEYS if role == 'controller' else ('NATS_PASSWORD', 'REGISTRATION_TOKEN'):
        if not re.fullmatch(r'[a-f0-9]{64}', values.get(key, '')):
            fail(f'{key} must be a generated 64-character hex secret')
    for key in ('CONTROLLER_IMAGE', 'POSTGRES_IMAGE', 'NATS_IMAGE') if role == 'controller' else ('WORKER_IMAGE',):
        if not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}', values.get(key, '')):
            fail(f'{key} requires a SHA256 digest pin')
    if role == 'controller' and values['CONTROLLER_BIND_IP'] != '127.0.0.1':
        if not (root / 'admin-bootstrap.json').is_file():
            fail('Bootstrap the administrator on loopback before publishing the controller')
    if role == 'worker':
        private_ip(values['CONTROLLER_IP'])
        for key in ('VIDEO_GID', 'RENDER_GID'):
            if not values.get(key, '').isdigit():
                fail(f'{key} must be the GPU host group numeric ID')
    return values


def compose(root, values, *arguments, **kwargs):
    env = os.environ.copy()
    # Shell environment must not silently override the generated dotenv file.
    for key in values:
        env.pop(key, None)
    command = ['docker', 'compose', '--project-name', values['PROJECT_NAME'],
               '--env-file', str(root / '.env'), '-f', str(PACKAGE / f"{values['ROLE']}.compose.yaml")]
    if values['ROLE'] == 'controller' and values.get('AI_NETWORK'):
        command.extend(['-f', str(PACKAGE / 'platform.compose.yaml')])
    command.extend(arguments)
    return subprocess.run(command, env=env, check=True, **kwargs)


def bootstrap(root, values):
    if values['ROLE'] != 'controller' or values['CONTROLLER_BIND_IP'] != '127.0.0.1':
        fail('Administrator bootstrap requires a loopback-only controller')
    password = getpass.getpass('Administrator password (not stored by this script): ')
    if len(password) < 12 or password != getpass.getpass('Repeat password: '):
        fail('Use matching passwords of at least 12 characters')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    payload = json.dumps({'email': values['ADMIN_EMAIL'], 'name': 'Homelab administrator',
                          'password': password}).encode()
    for endpoint in ('register', 'login'):
        request = urllib.request.Request(f'http://127.0.0.1:18080/api/auth/{endpoint}', payload,
                                         {'Content-Type': 'application/json'})
        with opener.open(request, timeout=20) as response:
            body = json.load(response)
        if body.get('user', {}).get('role') == 'admin':
            (root / 'admin-bootstrap.json').write_text(json.dumps({'email': values['ADMIN_EMAIL']}) + '\n')
            print('Administrator verified. Controller remains on loopback until publish is run.')
            return
    fail('Could not verify an active administrator; controller remains private')


def export_worker(args, root, values):
    if values['ROLE'] != 'controller':
        fail('Export workers from the controller configuration')
    controller = private_ip(values['CONTROLLER_BIND_IP'])
    worker = private_ip(args.worker_ip)
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', args.name):
        fail('Use a lowercase worker name such as desk or m5')
    target = args.output.resolve()
    if target.exists():
        fail('Worker credential export already exists; choose a new output path')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_env(target, dict(ROLE='worker', PROJECT_NAME=f'nexus-localai-{args.name}',
                          WORKER_IMAGE=values['WORKER_IMAGE'], CONTROLLER_IP=controller,
                          WORKER_BIND_IP=worker, NODE_NAME=args.name,
                          REGISTRATION_TOKEN=values['REGISTRATION_TOKEN'],
                          NATS_PASSWORD=values['NATS_PASSWORD'], VRAM_BUDGET='80%'))
    print(f'Worker credentials written to {target}; transfer privately, then init-worker on that host.')


def init_worker(args, root):
    values = load_config(args.credentials)
    if values.get('ROLE') != 'worker' or 'POSTGRES_PASSWORD' in values or 'AUTH_HMAC_SECRET' in values:
        fail('Expected a worker-only credential export')
    if (root / '.env').exists():
        fail('Worker configuration already exists')
    if root.exists() and any(root.iterdir()):
        fail('Worker state is not empty; recover the existing configuration instead of reinitializing')
    private_ip(values['WORKER_BIND_IP'])
    private_ip(values['CONTROLLER_IP'])
    gids = {key: str(grp.getgrnam(group).gr_gid) for key, group in [('VIDEO_GID', 'video'), ('RENDER_GID', 'render')]}
    if not Path('/dev/dri').exists() or not Path('/dev/kfd').exists():
        fail('Prepare AMD host GPU drivers first: /dev/dri and /dev/kfd are required')
    prepare(root, 'worker')
    values.update(gids, STATE_ROOT=str(root))
    write_env(root / '.env', values)
    configuration(root)
    print('Worker initialized; launch it with up and approve it in the controller UI.')


def backup(args, root, values):
    if values['ROLE'] != 'controller':
        fail('This backup command captures controller state; worker caches are handled separately')
    if not (root / 'admin-bootstrap.json').is_file():
        fail('Bootstrap the administrator before creating an installation backup')
    target = args.destination.resolve() / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target.mkdir(parents=True, mode=0o700)
    target.chmod(0o700)
    states = compose(root, values, 'ps', '--status', 'running', '--services', capture_output=True, text=True).stdout.splitlines()
    was_running = 'controller' in states
    compose(root, values, 'stop', 'controller')
    try:
        with (target / 'database.dump').open('wb') as output:
            compose(root, values, 'exec', '-T', 'postgres', 'pg_dump', '-U', 'localai', '-d', 'localai',
                    '--format=custom', '--no-owner', stdout=output)
        archives = {
            'data.tar.gz': ['tar', '-C', '/data', '-czf', '-', '.'],
            'configuration.tar.gz': ['tar', '-C', '/configuration', '-czf', '-', '.'],
            'models-config.tar.gz': ['bash', '-o', 'pipefail', '-c',
                "cd /models && find . -type f \\( -name '*.yaml' -o -name '*.yml' -o -name '*.json' \\) -print0 | tar --null -T - -czf -"],
        }
        for filename, command in archives.items():
            with (target / filename).open('wb') as output:
                compose(root, values, 'run', '--rm', '--no-deps', '-T', '--entrypoint', command[0],
                        'controller', *command[1:], stdout=output)
        shutil.copyfile(root / '.env', target / 'controller.env')
        shutil.copyfile(root / 'admin-bootstrap.json', target / 'admin-bootstrap.json')
        manifest = {}
        for path in target.iterdir():
            path.chmod(0o600)
            with path.open('rb') as source:
                manifest[path.name] = hashlib.file_digest(source, 'sha256').hexdigest()
        (target / 'checksums.json').write_text(json.dumps(manifest, indent=2) + '\n')
        print(f'Backup complete: {target}. Contains secrets; encrypt before off-host storage.')
    finally:
        if was_running:
            compose(root, values, 'up', '-d', '--wait', '--wait-timeout', '300', 'controller')


def verify_backup(path):
    expected = {'database.dump', 'data.tar.gz', 'configuration.tar.gz', 'models-config.tar.gz',
                'controller.env', 'admin-bootstrap.json'}
    manifest = json.loads((path / 'checksums.json').read_text())
    if set(manifest) != expected:
        fail('Backup manifest has missing or unexpected files')
    for name, digest in manifest.items():
        with (path / name).open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != digest:
                fail(f'Backup checksum failed: {name}')
    for name in ('data.tar.gz', 'configuration.tar.gz', 'models-config.tar.gz'):
        with tarfile.open(path / name) as archive:
            for member in archive:
                if member.name.startswith('/') or '..' in Path(member.name).parts or not (member.isfile() or member.isdir()):
                    fail(f'Unsafe archive entry in {name}; restore manually after inspection')


def restore(args, root):
    source = args.backup.resolve()
    verify_backup(source)
    if root.exists() and any(root.iterdir()):
        fail('Restore requires a new empty --state-dir; existing installations are never overwritten')
    values = load_config(source / 'controller.env')
    values.update(STATE_ROOT=str(root), PROJECT_NAME=args.project_name, CONTROLLER_BIND_IP='127.0.0.1',
                  LOCALAI_BASE_URL='', OIDC_ISSUER='', OIDC_CLIENT_ID='', OIDC_CLIENT_SECRET='', DISABLE_LOCAL_AUTH='false')
    values.pop('AI_NETWORK', None)
    # An existing Postgres volume could contain a different installation.
    volume = subprocess.run(['docker', 'volume', 'ls', '--filter', f"name=^{args.project_name}_postgres-data$",
                             '--format', '{{.Name}}'], check=True, capture_output=True, text=True)
    if volume.stdout.strip():
        fail('Recovery project already has a PostgreSQL volume; choose a new project name')
    prepare(root, 'controller')
    write_env(root / '.env', values)
    values = configuration(root)
    compose(root, values, 'up', '-d', '--wait', '--wait-timeout', '120', 'postgres', 'nats')
    with (source / 'database.dump').open('rb') as input_file:
        compose(root, values, 'exec', '-T', 'postgres', 'pg_restore', '-U', 'localai', '-d', 'localai',
                '--clean', '--if-exists', '--no-owner', '--exit-on-error', stdin=input_file)
    for filename, directory in [('data.tar.gz', '/data'), ('configuration.tar.gz', '/configuration'),
                                ('models-config.tar.gz', '/models')]:
        with (source / filename).open('rb') as input_file:
            compose(root, values, 'run', '--rm', '--no-deps', '-T', '--entrypoint', 'tar', 'controller',
                    '-C', directory, '-xzf', '-', stdin=input_file)
    shutil.copyfile(source / 'admin-bootstrap.json', root / 'admin-bootstrap.json')
    print('State restored; controller is stopped and configured for loopback. Restore weights/backends before testing.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=PACKAGE / '.runtime/controller')
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init-controller')
    init.add_argument('--admin-email', required=True)
    init.add_argument('--project-name', default='nexus-localai-controller')
    for command in ('validate', 'up', 'restart', 'down', 'status', 'logs', 'bootstrap-admin', 'sync-config'):
        commands.add_parser(command)
    publish = commands.add_parser('publish')
    publish.add_argument('--ip', required=True)
    export = commands.add_parser('export-worker')
    export.add_argument('--name', required=True)
    export.add_argument('--worker-ip', required=True)
    export.add_argument('--output', type=Path, required=True)
    worker = commands.add_parser('init-worker')
    worker.add_argument('--credentials', type=Path, required=True)
    save = commands.add_parser('backup')
    save.add_argument('--destination', type=Path, required=True)
    recovery = commands.add_parser('restore')
    recovery.add_argument('--backup', type=Path, required=True)
    recovery.add_argument('--project-name', required=True)
    check = commands.add_parser('verify-backup')
    check.add_argument('--backup', type=Path, required=True)
    args = parser.parse_args()
    root = args.state_dir.resolve()
    os.umask(0o077)
    if args.command == 'init-controller':
        initialize(args, root)
        return
    if args.command == 'init-worker':
        init_worker(args, root)
        return
    if args.command == 'restore':
        restore(args, root)
        return
    if args.command == 'verify-backup':
        verify_backup(args.backup)
        print('Backup checksums and archive paths verified.')
        return
    values = configuration(root)
    if args.command == 'validate':
        compose(root, values, 'config', '--quiet')
        print('Configuration valid; no credentials printed and no containers started.')
    elif args.command == 'up':
        compose(root, values, 'config', '--quiet')
        compose(root, values, 'up', '-d', '--wait', '--wait-timeout', '300')
    elif args.command == 'restart':
        compose(root, values, 'up', '-d', '--no-deps', '--force-recreate', '--wait', '--wait-timeout', '300',
                'controller' if values['ROLE'] == 'controller' else 'worker')
    elif args.command in ('down', 'status', 'logs'):
        compose(root, values, *{'down': ['down'], 'status': ['ps'], 'logs': ['logs', '--tail', '100']}[args.command])
    elif args.command == 'bootstrap-admin':
        bootstrap(root, values)
    elif args.command == 'publish':
        if values['ROLE'] != 'controller' or not (root / 'admin-bootstrap.json').exists():
            fail('Bootstrap an administrator before publishing')
        values['CONTROLLER_BIND_IP'] = private_ip(args.ip)
        write_env(root / '.env', values)
        print('Tailscale binding saved; run up to apply it. No firewall or tailnet policy was changed.')
    elif args.command == 'export-worker':
        export_worker(args, root, values)
    elif args.command == 'sync-config':
        if values['ROLE'] != 'controller':
            fail('Only the controller owns placement configuration')
        shutil.copyfile(PACKAGE / 'config/scheduling.yaml', root / 'configuration/scheduling.yaml')
        print('Placement file copied; run restart after taking a backup to apply startup scheduling.')
    elif args.command == 'backup':
        backup(args, root, values)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, tarfile.TarError, subprocess.CalledProcessError, urllib.error.URLError) as error:
        # Do not echo process arguments, HTTP bodies, passwords, or dotenv values.
        print(f'Failed: {type(error).__name__}. ' + (str(error) if isinstance(error, ValueError) else
              'Check prerequisites, connectivity and local service logs; sensitive details suppressed.'), file=sys.stderr)
        sys.exit(1)
