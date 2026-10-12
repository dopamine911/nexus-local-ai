#!/usr/bin/env python3
"""Reproducible private platform lifecycle; Docker Compose implements the services."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tarfile

PACKAGE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('localai_lab', PACKAGE.parent / 'localai/lab.py')
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)
SECRET_KEYS = ('AUTH_DB_PASSWORD', 'AUTH_SECRET_KEY', 'AUTH_BOOTSTRAP_PASSWORD',
               'HOMARR_ENCRYPTION_KEY', 'HOMARR_OIDC_SECRET', 'LOCALAI_OIDC_SECRET',
               'BESZEL_OIDC_SECRET', 'SEARCH_SECRET', 'RESTIC_PASSWORD')
APPS = ('authentik', 'auth-worker', 'homarr', 'beszel', 'caddy', 'searxng', 'memory')
VOLUMES = ('caddy-data', 'caddy-config', 'auth-data', 'auth-media', 'homarr-data', 'beszel-data', 'memory-data', 'memory-config')


def validate_values(values, root):
    if values.get('STATE_ROOT') != str(root):
        lab.fail('STATE_ROOT must match --state-dir')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', values.get('PROJECT_NAME', '')):
        lab.fail('Invalid project name')
    if not re.fullmatch(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', values.get('LAB_DOMAIN', '')):
        lab.fail('Use a DNS domain such as lab.home.arpa')
    lab.private_ip(values.get('BIND_IP', ''), loopback=True)
    if set(values.get('ENABLED_PROFILES', '').split(',')) - {'', 'research'}:
        lab.fail('Only research is a long-running optional profile')
    for key in SECRET_KEYS:
        if not re.fullmatch(r'[a-f0-9]{64}', values.get(key, '')):
            lab.fail(f'{key} requires a generated hex secret')
    for key, value in values.items():
        if key.endswith('_IMAGE') and not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}', value):
            lab.fail(f'{key} requires a registry digest')
    if values['BIND_IP'] != '127.0.0.1' and not (root / 'bootstrap-reviewed.json').exists():
        lab.fail('Complete initial account setup on loopback before publishing')


def config(root):
    if (root / '.env').stat().st_mode & 0o077:
        lab.fail('Configuration permissions must be 600')
    values = lab.load_config(root / '.env')
    validate_values(values, root)
    return values


def compose(root, values, *arguments, **kwargs):
    env = os.environ.copy()
    for key in values:
        env.pop(key, None)
    env.pop('COMPOSE_PROFILES', None)
    command = ['docker', 'compose', '--project-name', values['PROJECT_NAME'],
               '--env-file', str(root / '.env'), '-f', str(PACKAGE / 'compose.yaml')]
    for profile in filter(None, values['ENABLED_PROFILES'].split(',')):
        command += ['--profile', profile]
    return subprocess.run(command + list(arguments), env=env, check=True, **kwargs)


def render(root, values):
    domain = values['LAB_DOMAIN']
    entries = []
    for slug, callback in [('homarr', f'https://{domain}/api/auth/callback/oidc'),
                           ('localai', f'https://ai.{domain}/api/auth/oidc/callback'),
                           ('beszel', f'https://health.{domain}/api/oauth2-redirect')]:
        email_scope = '!KeyOf verified-email' if slug == 'beszel' else '!Find [authentik_providers_oauth2.scopemapping, [managed, goauthentik.io/providers/oauth2/scope-email]]'
        entries.append(f'''  - model: authentik_providers_oauth2.oauth2provider
    id: {slug}-provider
    identifiers: {{name: Nexus {slug}}}
    attrs:
      client_id: {slug}
      client_secret: !Env {slug.upper()}_OIDC_SECRET
      client_type: confidential
      issuer_mode: per_provider
      authorization_flow: !Find [authentik_flows.flow, [slug, default-provider-authorization-implicit-consent]]
      invalidation_flow: !Find [authentik_flows.flow, [slug, default-provider-invalidation-flow]]
      signing_key: !Find [authentik_crypto.certificatekeypair, [name, authentik Self-signed Certificate]]
      redirect_uris:
        - matching_mode: strict
          url: {callback}
          redirect_uri_type: authorization
      property_mappings:
        - !Find [authentik_providers_oauth2.scopemapping, [managed, goauthentik.io/providers/oauth2/scope-openid]]
        - {email_scope}
        - !Find [authentik_providers_oauth2.scopemapping, [managed, goauthentik.io/providers/oauth2/scope-profile]]
        - !Find [authentik_providers_oauth2.scopemapping, [managed, goauthentik.io/providers/oauth2/scope-offline_access]]
  - model: authentik_core.application
    id: {slug}-app
    identifiers: {{slug: {slug}}}
    attrs:
      name: {slug.title()}
      provider: !KeyOf {slug}-provider
      policy_engine_mode: any
  - model: authentik_policies.policybinding
    identifiers: {{target: !KeyOf {slug}-app, order: 0}}
    attrs: {{group: !KeyOf users}}
  - model: authentik_policies.policybinding
    identifiers: {{target: !KeyOf {slug}-app, order: 1}}
    attrs: {{user: !Find [authentik_core.user, [username, akadmin]]}}
''')
    blueprint = (PACKAGE / 'config/authentik.yaml.template').read_text()
    blueprint = blueprint.replace('@@DOMAIN@@', domain).replace('@@OIDC_ENTRIES@@', ''.join(entries).rstrip())
    (root / 'config/blueprints/nexus.yaml').write_text(blueprint)
    shutil.copyfile(PACKAGE / 'config/Caddyfile', root / 'config/Caddyfile')
    settings = {'use_default_settings': True, 'server': {'secret_key': values['SEARCH_SECRET'],
                'limiter': False, 'image_proxy': True, 'bind_address': '0.0.0.0', 'port': 8080}, 'search': {'formats': ['html', 'json']},
                'valkey': {'url': 'valkey://valkey:6379/0'}}
    # JSON is a YAML subset; stdlib keeps lifecycle tooling dependency-free.
    (root / 'config/searxng/settings.yml').write_text(json.dumps(settings, indent=2) + '\n')
    for path in (root / 'config').rglob('*'):
        path.chmod(0o755 if path.is_dir() else 0o644)
    links = {label: f'https://{host}' for label, host in [('Portal', domain), ('Identity', f'auth.{domain}'),
             ('Models and chat', f'ai.{domain}'), ('Health', f'health.{domain}'), ('Research', f'search.{domain}'),
             ('Images', f'images.{domain}') ]}
    (root / 'dashboard-links.json').write_text(json.dumps(links, indent=2) + '\n')


def prepare(root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    for folder in ('config/blueprints', 'config/searxng', 'trust', 'snapshots'):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / 'config').chmod(0o755)
    # Certificates are public. Non-root dashboard containers must traverse this directory.
    (root / 'trust').chmod(0o755)


def initialize(args, root):
    if root.exists() and any(root.iterdir()):
        lab.fail('Initialization requires an empty state directory; it never rotates existing secrets')
    values = lab.read_env(PACKAGE / 'images.env')
    values.update(STATE_ROOT=str(root), PROJECT_NAME=args.project_name, LAB_DOMAIN=args.domain,
                  BIND_IP='127.0.0.1', ADMIN_EMAIL=args.admin_email, ENABLED_PROFILES='',
                  HOMARR_AUTH_PROVIDERS='credentials')
    values.update({key: secrets.token_hex(32) for key in SECRET_KEYS})
    validate_values(values, root)
    prepare(root)
    lab.write_env(root / '.env', values)
    render(root, values)
    print(f'Initialized private configuration in {root}; no credentials printed.')


def export_ca(root, values):
    # Read existing CA; never manufacture a new root during export or copy its private key.
    compose(root, values, 'cp', 'caddy:/data/caddy/pki/authorities/local/root.crt', str(root / 'trust/root.crt'))
    compose(root, values, 'cp', 'caddy:/etc/ssl/certs/ca-certificates.crt', str(root / 'trust/public-ca.crt'))
    for name in ('root.crt', 'public-ca.crt'):
        path = root / 'trust' / name
        if '-----BEGIN CERTIFICATE-----' not in path.read_text():
            lab.fail('CA export was not a PEM certificate')
        path.chmod(0o644)
    bundle = root / 'trust/ca-bundle.crt'
    bundle.write_text((root / 'trust/public-ca.crt').read_text() + '\n' + (root / 'trust/root.crt').read_text())
    bundle.chmod(0o644)
    print('Public CA and trust bundle exported; install root.crt on authorized clients after verifying its fingerprint.')


def connect_localai(root, values, controller_root):
    controller_root = controller_root.resolve()
    target = lab.configuration(controller_root)
    if target['ROLE'] != 'controller' or not (controller_root / 'admin-bootstrap.json').exists():
        lab.fail('Bootstrap the LocalAI administrator before enabling OIDC')
    if not (root / 'trust/ca-bundle.crt').exists():
        lab.fail('Run export-ca first')
    trust = controller_root / 'configuration/trust'
    trust.mkdir(exist_ok=True)
    trust.chmod(0o755)
    shutil.copyfile(root / 'trust/ca-bundle.crt', trust / 'ca-bundle.crt')
    (trust / 'ca-bundle.crt').chmod(0o644)
    domain = values['LAB_DOMAIN']
    target.update(AI_NETWORK=values['PROJECT_NAME'] + '-ai', LOCALAI_BASE_URL=f'https://ai.{domain}',
                  OIDC_ISSUER=f'https://auth.{domain}/application/o/localai/', OIDC_CLIENT_ID='localai',
                  OIDC_CLIENT_SECRET=values['LOCALAI_OIDC_SECRET'], DISABLE_LOCAL_AUTH='false')
    lab.write_env(controller_root / '.env', target)
    lab.compose(controller_root, target, 'config', '--quiet')
    print('LocalAI proxy network and OIDC configured; run lab.py restart to apply. Recovery login remains enabled.')


def backup(root, values, destination):
    if destination.exists():
        lab.fail('Backup destination already exists')
    active = subprocess.run(['docker', 'ps', '--filter', f"label=com.docker.compose.project={values['PROJECT_NAME']}",
                             '--filter', 'label=com.docker.compose.service=memory', '--format', '{{.ID}}'],
                            check=True, capture_output=True, text=True)
    if active.stdout.strip():
        lab.fail('Close active Basic Memory MCP sessions before snapshotting its database')
    destination.mkdir(parents=True, mode=0o700)
    running = compose(root, values, 'ps', '--services', '--status', 'running', capture_output=True, text=True)
    stopped = [name for name in running.stdout.splitlines() if name in APPS]
    if 'auth-db' not in running.stdout.splitlines():
        lab.fail('Start the platform database before taking a consistent backup')
    try:
        if stopped:
            compose(root, values, 'stop', *stopped)
        with (destination / 'database.dump').open('wb') as output:
            compose(root, values, 'exec', '-T', 'auth-db', 'pg_dump', '-U', 'authentik', '-d', 'authentik',
                    '--format=custom', '--no-owner', stdout=output)
        with (destination / 'volumes.tar.gz').open('wb') as output:
            compose(root, values, 'run', '--rm', '--no-deps', '-T', 'snapshot', '-C', '/state', '-czf', '-', *VOLUMES,
                    stdout=output)
        with tarfile.open(destination / 'configuration.tar.gz', 'w:gz') as archive:
            for name in ('.env', 'config', 'trust', 'dashboard-links.json', 'bootstrap-reviewed.json'):
                if (root / name).exists():
                    archive.add(root / name, arcname=name)
        manifest = {}
        for path in destination.iterdir():
            path.chmod(0o600)
            with path.open('rb') as source:
                manifest[path.name] = hashlib.file_digest(source, 'sha256').hexdigest()
        (destination / 'checksums.json').write_text(json.dumps(manifest, indent=2) + '\n')
        verify_backup(destination)
        print(f'Consistent snapshot saved in {destination}; encrypt off-host with restic.')
    finally:
        if stopped:
            compose(root, values, 'up', '-d', '--wait', '--wait-timeout', '300', *stopped)


def verify_backup(source):
    manifest = json.loads((source / 'checksums.json').read_text())
    if set(manifest) != {'database.dump', 'volumes.tar.gz', 'configuration.tar.gz'}:
        lab.fail('Unexpected backup manifest')
    for name, digest in manifest.items():
        with (source / name).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                lab.fail(f'Checksum mismatch: {name}')
    for name in ('volumes.tar.gz', 'configuration.tar.gz'):
        with tarfile.open(source / name) as archive:
            seen = set()
            for member in archive:
                parts = Path(member.name).parts
                if parts in seen:
                    lab.fail('Duplicate archive path')
                seen.add(parts)
                # Pinned Authentik Dockerfile deliberately ships this compatibility link.
                # /media is separately persisted; no archive member may traverse the link.
                compatibility_link = (name == 'volumes.tar.gz' and member.name == 'auth-data/media'
                                      and member.issym() and member.linkname == '/media')
                if compatibility_link:
                    continue
                if parts[:2] == ('auth-data', 'media') and len(parts) > 2:
                    lab.fail('Media content must restore through its dedicated volume, not a symlink')
                if member.name.startswith('/') or '..' in Path(member.name).parts or not (member.isfile() or member.isdir()):
                    lab.fail(f'Unsafe archive entry: {member.name}')
                if name == 'volumes.tar.gz' and Path(member.name).parts[0] not in VOLUMES:
                    lab.fail('Unexpected volume in backup')


def restore(root, args):
    source = args.backup.resolve()
    verify_backup(source)
    if root.exists() and any(root.iterdir()):
        lab.fail('Restore requires an empty state directory')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', args.project_name):
        lab.fail('Invalid recovery project name')
    existing = subprocess.run(['docker', 'volume', 'ls', '--format', '{{.Name}}'], check=True, capture_output=True, text=True)
    if any(name.startswith(args.project_name + '_') for name in existing.stdout.splitlines()):
        lab.fail('Recovery project already has volumes; select a fresh project name')
    prepare(root)
    with tarfile.open(source / 'configuration.tar.gz') as archive:
        archive.extractall(root, filter='data')
    values = lab.load_config(root / '.env')
    values.update(STATE_ROOT=str(root), PROJECT_NAME=args.project_name, BIND_IP='127.0.0.1', HOMARR_AUTH_PROVIDERS='credentials')
    lab.write_env(root / '.env', values)
    validate_values(values, root)
    compose(root, values, 'up', '-d', '--wait', '--wait-timeout', '120', 'auth-db')
    with (source / 'database.dump').open('rb') as stream:
        compose(root, values, 'exec', '-T', 'auth-db', 'pg_restore', '-U', 'authentik', '-d', 'authentik',
                '--no-owner', '--exit-on-error', stdin=stream)
    with (source / 'volumes.tar.gz').open('rb') as stream:
        compose(root, values, 'run', '--rm', '--no-deps', '-T', 'snapshot', '-C', '/state', '-xzf', '-', stdin=stream)
    print('Restored into a fresh loopback project. Start and test before publishing; reconnect LocalAI to the new network.')


def restic(root, values, args, *command):
    mount = args.nas_mount.resolve()
    repository = args.repository.resolve()
    if not os.path.ismount(mount) or not repository.is_relative_to(mount) or repository == mount:
        lab.fail('Repository must be a subdirectory of an actually mounted NAS; refusing local-disk fallback')
    repository.mkdir(exist_ok=True)
    env = os.environ.copy()
    env['RESTIC_PASSWORD'] = values['RESTIC_PASSWORD']
    # Environment passthrough keeps the password out of argv / process listings.
    subprocess.run(['docker', 'run', '--rm', '--network', 'none', '-e', 'RESTIC_PASSWORD',
                    '-v', f'{repository}:/repository', '-v', f'{args.source.resolve()}:/snapshot:ro',
                    values['RESTIC_IMAGE'], '-r', '/repository', *command], check=True, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=PACKAGE / '.runtime/platform')
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    init.add_argument('--domain', default='lab.home.arpa')
    init.add_argument('--project-name', default='nexus-platform')
    init.add_argument('--admin-email', required=True)
    for name in ('validate', 'up', 'restart', 'down', 'status', 'logs', 'export-ca', 'sync-config', 'enable-oidc'):
        commands.add_parser(name)
    publish = commands.add_parser('publish')
    publish.add_argument('--ip', required=True)
    publish.add_argument('--accounts-reviewed', action='store_true', required=True)
    research = commands.add_parser('research')
    research.add_argument('mode', choices=('enable', 'disable'))
    connect = commands.add_parser('connect-localai')
    connect.add_argument('--controller-state', type=Path, required=True)
    save = commands.add_parser('backup')
    save.add_argument('--destination', type=Path, required=True)
    for name in ('restore', 'verify-backup'):
        recovery = commands.add_parser(name)
        recovery.add_argument('--backup', type=Path, required=True)
        if name == 'restore':
            recovery.add_argument('--project-name', required=True)
    encrypt = commands.add_parser('restic')
    encrypt.add_argument('operation', choices=('init', 'backup', 'check', 'snapshots'))
    encrypt.add_argument('--nas-mount', type=Path, required=True)
    encrypt.add_argument('--repository', type=Path, required=True)
    encrypt.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    root = args.state_dir.resolve()
    os.umask(0o077)
    if args.command == 'init':
        initialize(args, root)
        return
    if args.command == 'restore':
        restore(root, args)
        return
    if args.command == 'verify-backup':
        verify_backup(args.backup)
        print('Backup integrity and archive paths verified.')
        return
    values = config(root)
    if args.command == 'validate':
        compose(root, values, 'config', '--quiet')
    elif args.command in ('up', 'restart'):
        compose(root, values, 'config', '--quiet')
        recreate = ['--force-recreate'] if args.command == 'restart' else []
        compose(root, values, 'up', '-d', *recreate, '--wait', '--wait-timeout', '300')
    elif args.command in ('down', 'status', 'logs'):
        compose(root, values, *{'down': ['down'], 'status': ['ps'], 'logs': ['logs', '--tail', '100']}[args.command])
    elif args.command == 'export-ca':
        export_ca(root, values)
    elif args.command == 'sync-config':
        render(root, values)
        print('Tracked templates rendered. Run restart to apply bind-mounted config changes.')
    elif args.command == 'enable-oidc':
        if not (root / 'trust/ca-bundle.crt').exists():
            lab.fail('Export CA before enabling OIDC')
        values['HOMARR_AUTH_PROVIDERS'] = 'credentials,oidc'
        lab.write_env(root / '.env', values)
        print('Homarr OIDC enabled in configuration; run up to apply.')
    elif args.command == 'publish':
        values['BIND_IP'] = lab.private_ip(args.ip)
        (root / 'bootstrap-reviewed.json').write_text(json.dumps({'reviewed_at': datetime.now(timezone.utc).isoformat()}))
        lab.write_env(root / '.env', values)
        print('Tailscale binding saved; run up. DNS, firewall and CA trust remain operator configuration.')
    elif args.command == 'research':
        if args.mode == 'disable':
            compose(root, values, 'stop', 'searxng', 'valkey')
        values['ENABLED_PROFILES'] = 'research' if args.mode == 'enable' else ''
        lab.write_env(root / '.env', values)
        print('Research profile saved; run up to apply.')
    elif args.command == 'connect-localai':
        connect_localai(root, values, args.controller_state)
    elif args.command == 'backup':
        backup(root, values, args.destination.resolve())
    elif args.command == 'restic':
        if args.operation == 'backup':
            if not args.source.is_dir() or not any(args.source.iterdir()):
                lab.fail('Backup source must be a nonempty snapshot directory')
            restic(root, values, args, 'backup', '/snapshot', '--tag', 'nexus')
        else:
            restic(root, values, args, args.operation)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
