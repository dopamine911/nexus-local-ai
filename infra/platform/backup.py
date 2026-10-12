#!/usr/bin/env python3
"""Quiesce platform and LocalAI independently; encrypt their verified snapshots on NAS."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import stack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    settings = json.loads(args.config.read_text())
    values = stack.config(Path(settings['platform_state']).resolve())
    mount = Path(settings['nas_mount']).resolve()
    repository = Path(settings['repository']).resolve()
    if not os.path.ismount(mount) or not repository.is_relative_to(mount) or repository == mount:
        stack.lab.fail('NAS is not mounted or repository is outside its mount; no snapshots taken')
    active_jobs = subprocess.run(['docker', 'ps', '--filter', 'label=com.docker.compose.project=nexus-workloads',
                                  '--format', '{{.ID}}'], check=True, capture_output=True, text=True)
    if active_jobs.stdout.strip():
        stack.lab.fail('Stop image/training jobs before the scheduled snapshot window')
    os.umask(0o077)
    staging = Path(settings['staging_root']).resolve() / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    staging.mkdir(parents=True, mode=0o700)
    # Independent application snapshots, not a single cross-application transaction.
    stack.backup(Path(settings['platform_state']).resolve(), values, staging / 'platform')
    stack.verify_backup(staging / 'platform')
    subprocess.run([sys.executable, str(stack.PACKAGE.parent / 'localai/lab.py'), '--state-dir', settings['localai_state'],
                    'backup', '--destination', str(staging / 'localai')], check=True)
    stack.lab.verify_backup(staging / 'localai')
    workload = Path(settings['workload_state']).resolve()
    if workload.exists():
        # Outputs/recipes only; training/image jobs must be stopped for a consistent copy.
        for name in ('training', 'outputs', 'comfyui/user', 'comfyui/output'):
            source = workload / name
            if source.exists():
                shutil.copytree(source, staging / 'workloads' / name)
    restic_args = argparse.Namespace(nas_mount=mount, repository=repository, source=staging)
    stack.restic(None, values, restic_args, 'backup', '/snapshot', '--tag', 'nexus')
    stack.restic(None, values, restic_args, 'check')
    # Failed uploads retain staging; successful uploads need not fill the 1 TB NVMe with plaintext.
    if settings.get('keep_staging', False):
        (staging / 'encrypted-success.json').write_text(json.dumps({'completed_at': datetime.now(timezone.utc).isoformat()}))
    else:
        shutil.rmtree(staging)
    print('Encrypted NAS backup and repository metadata check passed.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
