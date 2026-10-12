#!/usr/bin/env python3
"""Optional AMD workloads on machine 2; no automatic driver or model installation."""
import argparse
import grp
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys

PACKAGE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('localai_lab', PACKAGE.parent / 'localai/lab.py')
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=PACKAGE / '.runtime/workloads')
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    init.add_argument('--platform-project', default='nexus-platform')
    for name in ('validate', 'probe', 'build', 'image-up', 'image-down', 'train'):
        command = commands.add_parser(name)
        if name in ('probe', 'image-up', 'train'):
            command.add_argument('--gpu-reserved', action='store_true', required=True)
    args = parser.parse_args()
    root = args.state_dir.resolve()
    os.umask(0o077)
    if args.command == 'init':
        if root.exists() and any(root.iterdir()):
            lab.fail('Initialization requires an empty workload state directory')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', args.platform_project):
            lab.fail('Invalid platform project name')
        if not Path('/dev/kfd').exists() or not Path('/dev/dri').exists():
            lab.fail('Initialize on the AMD GPU host after installing and verifying its driver')
        values = lab.read_env(PACKAGE / 'images.env') | lab.read_env(PACKAGE / 'source.env')
        values.update(STATE_ROOT=str(root), AI_NETWORK=args.platform_project + '-ai', UID_NUM=str(os.getuid()),
                      GID_NUM=str(os.getgid()), VIDEO_GID=str(grp.getgrnam('video').gr_gid),
                      RENDER_GID=str(grp.getgrnam('render').gr_gid))
        root.mkdir(parents=True, mode=0o700)
        for folder in ('comfyui', 'training', 'models', 'datasets', 'outputs'):
            (root / folder).mkdir()
        lab.write_env(root / '.env', values)
        print('Initialized GPU workload directories. Reserve the GPU before running image or training jobs.')
        return
    values = lab.load_config(root / '.env')
    if values['STATE_ROOT'] != str(root) or (root / '.env').stat().st_mode & 0o077:
        lab.fail('Workload state path or configuration permissions are invalid')
    if not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}', values.get('ROCM_IMAGE', '')):
        lab.fail('ROCm image must be pinned by digest')
    if not re.fullmatch(r'[a-f0-9]{40}', values.get('COMFY_COMMIT', '')) or not re.fullmatch(r'[a-f0-9]{64}', values.get('COMFY_ARCHIVE_SHA256', '')):
        lab.fail('ComfyUI source commit and archive checksum must be pinned')
    env = os.environ.copy()
    for key in values:
        env.pop(key, None)
    env.pop('COMPOSE_PROFILES', None)
    command = ['docker', 'compose', '-p', 'nexus-workloads', '--env-file', str(root / '.env'),
               '-f', str(PACKAGE / 'compose.yaml')]
    actions = {'validate': ['--profile', 'image', '--profile', 'training', '--profile', 'tools', 'config', '--quiet'],
               'probe': ['run', '--rm', '--no-deps', '-T', 'gpu-probe'],
               'build': ['build', 'comfyui'], 'image-up': ['up', '-d', 'comfyui'],
               'image-down': ['stop', 'comfyui'], 'train': ['run', '--rm', '--no-deps', '-T', 'training']}
    if args.command == 'train' and not (root / 'training/train.py').is_file():
        lab.fail('Supply a tracked training recipe at training/train.py before starting a job')
    subprocess.run(command + actions[args.command], env=env, check=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
