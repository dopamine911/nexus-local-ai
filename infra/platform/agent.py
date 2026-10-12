#!/usr/bin/env python3
"""Initialize / start a Beszel agent using operator-issued per-system credentials."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import stack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    init.add_argument('--credentials', type=Path, required=True)
    init.add_argument('--ca', type=Path, required=True)
    for name in ('validate', 'up', 'down', 'status'):
        commands.add_parser(name)
    args = parser.parse_args()
    root = args.state_dir.resolve()
    os.umask(0o077)
    if args.command == 'init':
        if root.exists() and any(root.iterdir()):
            stack.lab.fail('Agent initialization requires an empty directory')
        values = json.loads(args.credentials.read_text())
        if set(values) != {'AGENT_IP', 'KEY', 'TOKEN', 'HUB_URL'}:
            stack.lab.fail('Credentials require only AGENT_IP, KEY, TOKEN and HUB_URL')
        stack.lab.private_ip(values['AGENT_IP'])
        if not values['KEY'].startswith(('ssh-ed25519 ', 'ssh-rsa ')) or not values['TOKEN'] or not values['HUB_URL'].startswith('https://'):
            stack.lab.fail('Use the SSH public key, system token and HTTPS hub URL issued by Beszel')
        certificate = args.ca.read_text()
        if '-----BEGIN CERTIFICATE-----' not in certificate:
            stack.lab.fail('Use the exported public Caddy CA certificate')
        root.mkdir(parents=True, mode=0o700)
        (root / 'data').mkdir()
        (root / 'trust').mkdir(mode=0o755)
        (root / 'trust/root.crt').write_text(certificate)
        (root / 'trust/root.crt').chmod(0o644)
        values.update(AGENT_STATE_ROOT=str(root), BESZEL_AGENT_IMAGE=stack.lab.read_env(stack.PACKAGE / 'images.env')['BESZEL_AGENT_IMAGE'])
        stack.lab.write_env(root / '.env', values)
        print('Agent initialized; no tokens printed.')
        return
    values = stack.lab.load_config(root / '.env')
    if values['AGENT_STATE_ROOT'] != str(root) or (root / '.env').stat().st_mode & 0o077:
        stack.lab.fail('Agent state path or credential permissions are invalid')
    stack.lab.private_ip(values['AGENT_IP'])
    if not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}', values.get('BESZEL_AGENT_IMAGE', '')):
        stack.lab.fail('Agent image must be pinned by digest')
    env = os.environ.copy()
    for key in values:
        env.pop(key, None)
    command = ['docker', 'compose', '-p', 'nexus-health-agent', '--env-file', str(root / '.env'),
               '-f', str(stack.PACKAGE / 'agent.compose.yaml')]
    actions = {'validate': ['config', '--quiet'], 'up': ['up', '-d', '--wait'], 'down': ['down'], 'status': ['ps']}
    subprocess.run(command + actions[args.command], env=env, check=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
