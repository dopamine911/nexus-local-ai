# Backup, recovery, upgrades and benchmarks

## Secrets and recovery custody

Private state `.env` has mode 600 and lives below a 700 directory. It contains database credentials, Authentik bootstrap/recovery secrets, Homarr encryption key, OIDC secrets and the restic password. Docker administrators can read service environments; this design does not protect credentials from a compromised host administrator. Blueprint templates use secret references, not embedded values.

Keep the **restic password and repository location in an offline password manager/recovery copy**. A backup cannot recover its own encryption password without that external copy. Also retain a Git snapshot of this repository, pinned image availability/mirrors, NAS credentials, CA fingerprint, tailnet recovery access, and identity-provider local recovery login. Backups include the CA private key and application secrets and must be encrypted off-host.

## Consistent encrypted snapshots

`stack.py backup` stops running platform writers, exports the Authentik database with `pg_dump`, archives application volumes and private configuration, verifies checksums/archive paths, then restores the previously running services even if a backup step fails. Authentik media is separately persisted at `/media`: the pinned image's `/data/media` compatibility symlink is the only approved archive link, and payload traversal through it is rejected. Valkey/search caches and generated container files are rebuildable. Close memory sessions and stop image/training jobs before the backup window.

```bash
python3 infra/platform/stack.py --state-dir /srv/nexus/platform backup --destination /srv/nexus/backup-staging/platform-first
python3 infra/platform/stack.py verify-backup --backup /srv/nexus/backup-staging/platform-first
python3 infra/platform/stack.py --state-dir /srv/nexus/platform restic init --nas-mount /mnt/nexus-backups --repository /mnt/nexus-backups/restic/nexus --source /srv/nexus/backup-staging
```

`restic init` is performed once; the NAS mount must already exist and the repository's parent directory must be created on that mount. The script refuses an absent mount so a disconnected NAS cannot silently fill the NVMe. NFS permissions must permit the deployment operator/container UID to write; review root squash and encryption at the NAS boundary.

Copy `config/backup.example.json` to `/srv/nexus/platform/backup.json`, adjust paths, keep it private, then run:

```bash
python3 infra/platform/backup.py --config /srv/nexus/platform/backup.json
```

This orchestrates separately consistent platform and LocalAI snapshots, verifies both, includes existing training recipes/outputs and ComfyUI user/output directories, uploads with the pinned restic image, and runs a repository metadata check. Snapshots are **not a transaction spanning applications**. Successful plaintext staging is removed by default; add `"keep_staging": true` for a deliberate debugging copy. Failed runs retain staging in the private directory for diagnosis. Ensure free NVMe space for application dumps and user-created outputs.

Public model weights, downloadable backends and datasets are excluded. Preserve model provenance/checksums/licenses in the LocalAI artifact catalog, keep irreplaceable datasets/model weights on a separately backed-up NAS share, and store trained adapters/checkpoints under the included `outputs` directory. Large outputs may exceed available NVMe staging space; change backup policy before that happens.

`systemd/nexus-backup.service` and `.timer` are **installation templates** for a nightly run. Adjust user, repository and mount paths before installing them; no timer is enabled by initialization. The account requires Docker access. Prefer a quiet workload window; failed/missing NAS runs must be visible in `systemctl status`/journal. This phase does not configure external notifications.

Retention proposal: 7 daily + 4 weekly + 6 monthly restic snapshots. Prune only after an actual recovery test and an explicit recorded retention command. No automatic deletion of NAS snapshots is enabled. Periodically run `restic check --read-data` using an operator-maintained container command to verify payloads, not just metadata. NAS redundancy is not a second backup; copy irreplaceable encrypted state offsite periodically.

## Recovery drill

1. Recover the encryption password externally. Using the pinned restic image, restore the selected snapshot into a private empty local staging directory. Inspect `snapshots` first; do not guess which backup is current.
2. Run both platform and LocalAI `verify-backup` commands on their extracted directories.
3. Restore each into a **fresh project name and empty state directory**. Platform restore checks for existing volumes, preserves CA/application encryption keys, restores database/volumes, and leaves applications stopped with loopback binding.

```bash
python3 infra/platform/stack.py --state-dir /srv/nexus/recovered-platform restore --backup /srv/nexus/recovered-snapshot/platform --project-name nexus-platform-recovery
python3 infra/platform/stack.py --state-dir /srv/nexus/recovered-platform up
python3 infra/localai/lab.py --state-dir /srv/nexus/recovered-localai restore --backup /srv/nexus/recovered-snapshot/localai --project-name nexus-localai-recovery
```

4. Restore model weights/backends separately; recover image/training outputs into new workload directories. Test local administrator login, IdP discovery, dashboard state, model listing and authenticated inference. Existing recovered OIDC settings can still point to the old domain; keep recovery credentials available while isolating the drill.
5. Point test DNS at the restored host, test both users, then deliberately republish and reconnect LocalAI to the **recovery project's** AI network. Re-enroll agents if their private state was lost. Confirm the CA fingerprint stayed the same; a changed root requires deliberate client trust rotation.

Never use `down --volumes` on a real installation as a recovery step. A failed restore is diagnosed in its new project; it does not overwrite the old installation.

## Controlled upgrades

No Watchtower or unattended model/runtime upgrades. Record current Git revision, host kernel/driver versions, image digests and model checksums. Take and verify a consistent backup. Resolve candidate digests in the tracked `images.env`; copy reviewed pins into the private state `.env` using the same keys, validate, pull, and apply `up` during downtime. `sync-config` intentionally does not overwrite private image pins or rotate secrets.

Upgrade one application family at a time. Authentik server and worker must use the same digest. Treat PostgreSQL major-version changes as a dump/restore migration into a new volume; changing its image tag over existing data is not a migration. Homarr/PocketBase schemas can migrate forward; image downgrade alone may not undo them. Rollback after a schema migration restores the pre-upgrade snapshot into a fresh project with the old pins.

Before and after: credential recovery login, OIDC for both users, ordinary-user permissions, proxy rejection of unauthenticated search/image access, LocalAI workers/model download/inference, Beszel metrics, and encrypted backup. AMD kernel/ROCm changes additionally require the real tensor probe and comparable model/image workloads.

## Benchmark protocol

`tools/benchmark.py` records measured request duration, reported completion-token count and end-to-end tokens/sec, with one or two concurrent requests. It stores a prompt hash rather than content. It is **not TTFT or isolated decode speed**, and it does not judge correctness. Use a verified local model alias: locality checks cannot detect a server-side alias that routes to a cloud provider.

```bash
python3 infra/platform/tools/benchmark.py --url https://ai.lab.home.arpa/v1 --model coding-fast --api-key-file /srv/nexus/private/localai.key --prompt-file benchmarks/coding.txt --ca /srv/nexus/platform/trust/root.crt --runs 3 --concurrency 1 --output /srv/nexus/results/coding-fast-single.json
```

Create the prompt fixture in the repository before running. Repeat cold/warm loads, the same context length and quantization, and concurrency 2. Alongside results record backend/model hash, machine, power limit, kernel/driver, image digest, scheduling config and Beszel temperature/RAM/VRAM history. Compare fast/balanced/deep presets on coding tests and source-grounded research questions with manually reviewed answers. Measure image generation separately using a fixed workflow/seed/resolution/model; fine-tuning requires a fixed dataset split and held-out task score as well as time/VRAM.
