# Operations and recovery

## SSO and HTTPS integration

Use LocalAI's native OIDC with the proposed local Authentik instance. Set `LOCALAI_BASE_URL`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`, and `OIDC_CLIENT_SECRET` in the generated private dotenv file. In the identity provider register the callback `{LOCALAI_BASE_URL}/api/auth/oidc/callback`. Protect the client secret and test ordinary-user roles; a successful SSO login is not permission to administer models or workers.

Use the controller's existing local account as a recovery path while testing. `DISABLE_LOCAL_AUTH=false` preserves it. Only switch to OIDC-only after testing the actual recovery procedure. Changing OIDC settings requires `lab.py restart`. This package does not install Authentik or Caddy or assume a DNS provider/domain.

Caddy can route the final `https://ai.YOUR_DOMAIN` to controller port 18080, with streaming preserved. If the proxy runs in a container, its `localhost` is not the host: choose a reachable upstream deliberately. Keep direct staging/worker access on Tailscale; browser SSO is not a replacement for worker credentials. Tailnet policy should restrict NATS and worker gRPC to node identities, rather than all tailnet members.

Reference: [LocalAI OIDC](https://localai.io/docs/features/authentication/).

## Backup and recovery

`lab.py backup` stops the controller temporarily, creates a PostgreSQL custom-format dump, and archives mutable data, configuration, and model YAML/JSON. It copies the persistent HMAC secret and other private dotenv settings, then hashes the required files. The controller resumes if it was running. A failed backup is incomplete; do not treat the existence of its directory as success.

Suggested initial policy: nightly backup staging, 7 daily and 4 weekly encrypted copies on NAS, plus an independent encrypted copy of irreplaceable data. Choose encryption/key custody and retention implementation before scheduling. NAS parity is separate from backup. Generated backup directories are private, but contain plaintext secrets until encrypted; the staging filesystem itself must be trusted.

The checksum manifest detects corruption, not malicious tampering. Encryption/authentication of off-host backups and custody of recovery keys remain required. Back up the code repository, image pins, model artifact inventory, and known-good backend caches independently. No backup command removes old copies automatically.

Recovery into a **fresh directory and fresh project name**, on the appropriate recovery host:

```bash
python3 lab.py verify-backup --backup /PRIVATE/BACKUP/TIMESTAMP
python3 lab.py --state-dir .runtime/recovery restore \
  --backup /PRIVATE/BACKUP/TIMESTAMP --project-name nexus-localai-recovery
python3 lab.py --state-dir .runtime/recovery validate
python3 lab.py --state-dir .runtime/recovery up
```

Restore verifies checksums and archive paths before writing state. It refuses a nonempty target or an existing recovery project's PostgreSQL volume. It reuses backed-up passwords/HMAC, loads the database and file archives, and leaves the controller stopped and bound to loopback. It intentionally clears the old public URL/OIDC settings until those dependencies are checked.

Test the restored administrator and existing API keys, restore weights/backend artifacts, and test inference before republishing. Workers may need to register again and be approved. When recovering on a different Tailscale address, export new worker bundles using that address and update the worker configuration; do not initialize an existing worker over its state. NATS stream state and ongoing jobs are not recovered by this script. No distributed agent jobs are enabled in the pilot.

Actual dump/restore and restart behavior must be tested with running containers before this procedure becomes the accepted recovery plan.

## Upgrade procedure

1. Save an encrypted controller backup and preserve current model/backend artifacts and their inventory.
2. Resolve the new controller/worker and dependency image digests, inspect release notes, and update `images.env` for future installs. Existing installations retain their pins in the private `.env`; update both explicitly when promoting a release.
3. Restore into a separate pilot project; avoid competing worker stacks that bind the same ports or occupy the same GPU. Use separate machines or stop the normal worker while testing.
4. Test login, keys, worker approval/placement, file staging, representative models and two-user concurrency. Test backend upgrades separately from controller upgrades.
5. Schedule acceptable downtime, stop workers, promote compatible controller/worker versions, restart, and verify readiness and inference.
6. If rollback is needed, restore the prior DB/files and backend artifacts as well as image pins. An old image alone cannot undo a schema migration.

Containers will not auto-update. `restart` uses the saved digest. Backend/model installs initiated through the UI can still introduce new artifacts; record provenance before promotion.

## Benchmarks and monitoring

Compare Vulkan and ROCm with identical artifacts and contexts. Record host kernel/firmware/driver, image and backend digests, model/draft hashes, context/cache/parallel settings, cold-load time, first-token latency, prompt/generation rate, peak memory, thermals and power where measured. Include real coding tasks, research citation checks, cancellation and two-user contention rather than relying on generation rate alone.

Initially test 8K/32K contexts and then increase only with measured headroom. A fast profile should remain usable while the other user submits deeper work. Image generation and training share the R9700 with inference and require scheduling; this package does not implement a GPU scheduler.

LocalAI readiness checks detect service-level failures. Historical GPU metrics should come from Beszel or equivalent; a healthy controller does not prove correct model output or available GPU capacity.
