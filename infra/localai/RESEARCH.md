# Controller research and implementation boundaries

Research date: 2026-10-12. This package targets the release source at **v4.11.0 / 58830f7**. Public registry manifests were resolved directly; AMD64 appears in the selected controller/worker image manifests. This establishes availability and source compatibility, not successful execution on these hosts.

## Evidence and choices

| Finding | Implementation decision | Evidence |
| --- | --- | --- |
| Distributed state and accounts require PostgreSQL; NATS coordinates workers | Dedicated database and bus on Machine 2 | [Release Compose example](https://github.com/mudler/LocalAI/blob/v4.11.0/docker-compose.distributed.yaml) |
| Controller is a frontend; worker supervises per-model backends | Separate Compose projects, GPU devices only on workers | [Worker configuration](https://github.com/mudler/LocalAI/blob/v4.11.0/core/services/worker/config.go) |
| First user is administrator regardless of configured admin email | Loopback bootstrap, verified admin marker before publish, no email auto-promotion env setting | [Role assignment](https://github.com/mudler/LocalAI/blob/v4.11.0/core/http/auth/roles.go) |
| Account mode supports invite registration, OIDC, and persistent API-key hashing secret | Invite-only after first user; preserve HMAC secret through restore | [Controller CLI configuration](https://github.com/mudler/LocalAI/blob/v4.11.0/core/cli/run.go) |
| Worker downloads and direct gRPC use different addresses | Publish explicit host IPs, staging 50050, bounded gRPC 50051–50100 | [Worker configuration](https://github.com/mudler/LocalAI/blob/v4.11.0/core/services/worker/config.go) |
| Worker can otherwise serve files without a token | Nonempty generated enrollment token and registration-require-auth on both roles | [Worker startup](https://github.com/mudler/LocalAI/blob/v4.11.0/core/services/worker/worker.go) |
| NATS accepts a credentialed connection URL; LocalAI's require-auth switch specifically means JWT auth | Pilot uses shared NATS username/password; do not incorrectly enable JWT-only switches | [NATS connection](https://github.com/mudler/LocalAI/blob/v4.11.0/core/services/messaging/client.go), [auth configuration](https://github.com/mudler/LocalAI/blob/v4.11.0/pkg/natsauth/config.go) |
| Backend processes bind a wildcard address within their environment | Use Docker bridge isolation and explicit host-IP publishing, not host networking | [Backend supervisor](https://github.com/mudler/LocalAI/blob/v4.11.0/core/services/worker/supervisor.go) |
| Declarative scheduling is supported at controller startup | Repository-owned placement file, sync and recreate controller | [Controller CLI](https://github.com/mudler/LocalAI/blob/v4.11.0/core/cli/run.go) |

Confidence: 0.9 for these release-source contracts; caveat: container/image behavior and networking remain untested until host acceptance. Live documentation may describe changes after this release.

## Controller responsibilities

The controller authenticates users/API clients, stores node/placement state, manages models and routes requests. Workers register and receive backend lifecycle instructions through NATS; the controller stages artifacts and calls worker backends directly. This is scheduling independent models across machines, not combining both GPUs into one large distributed model.

Use ordinary PostgreSQL 17 for authentication/control state. This package does not configure pgvector or a shared memory database. If research/memory introduces vector storage, use a separately designed database or collection service rather than implicitly coupling it to the control-plane schema.

NATS JetStream has a persistent volume, but no agent execution workers are deployed. Shared bus credentials assume both worker machines are trusted. Individual worker JWT permissions and credential renewal are an improvement for a later phase. `LOCALAI_NATS_REQUIRE_AUTH` and `LOCALAI_DISTRIBUTED_REQUIRE_AUTH` require the JWT configuration; password authentication does not satisfy them. Registration authentication is explicitly enforced separately.

## Storage map

| State | Storage | Backup handling |
| --- | --- | --- |
| Users, keys, registry, placement, DB-managed UI settings | PostgreSQL named volume | Consistent custom-format pg_dump |
| Controller mutable files, uploads, generated output, local collections | `.runtime/controller/data` | Controller stopped for archive |
| Controller configuration directory and placement file | `.runtime/controller/configuration` | Archive; repository stores canonical scheduling |
| Model YAML/JSON configurations | Controller models directory | Archive configs only, recursively |
| GGUF/safetensors/other weights | Controller + worker models directories | Record immutable revision/checksum and maintain NAS archive separately |
| Downloaded backend binaries | Controller + worker backends directories | Preserve a known-good cache independently before upgrade |
| Worker transient staging/cache | Worker state directory | Reconstruct; do not treat as durable user data |
| NATS runtime streams | Named volume | Not restored by this pilot's controller recovery script; worker re-registration must be tested |
| DB/NATS/enrollment/HMAC/OIDC secrets | Private dotenv file | Included in private backup; encryption and recovery-key custody required |

The controller can hold a source copy of models staged to either worker. Account for duplication when budgeting the two 1 TB SSDs. A NAS archive does not mean every runtime mounts the NAS. Shared-model mode remains disabled because these hosts have distinct local model directories.

## Reproducibility gap and promotion

Container image content is digest-pinned. The model gallery index is release-pinned and startup gallery preloading is disabled. That does **not** pin everything referenced by a gallery: model configurations can reference mutable external files and backend gallery entries can point to `latest`/`master` OCI tags. Runtime backend installation remains available in this pilot.

Before promoting a working model, capture its full config, immutable model revision, hashes of every split file and any draft model, concrete backend OCI digest, context/cache settings, and measured results. Use artifacts.example.json as an inventory template. Mirror required model and backend artifacts to the NAS or another recovery store. A locally cached backend without provenance is not a reliable scratch rebuild.

The companion [platform package](../platform/README.md) now supplies OIDC, private HTTPS, historical host/GPU monitoring, and encrypted backup orchestration; [host provisioning](../hosts/README.md) targets the Ubuntu machine-2 baseline. These are deployment artifacts with isolated platform checks, not evidence of acceptance on either lab machine. The M5 OS/driver recipe and actual NAS integration remain host acceptance work.

## Acceptance checks on the actual hosts

1. Start only PostgreSQL/NATS/controller, create the first admin on loopback, and verify anonymous protected requests fail.
2. Publish to the actual Tailscale address; verify a trusted remote client succeeds and ordinary LAN/public paths cannot reach the services. No database/monitoring host ports should exist.
3. Verify wrong NATS credentials and wrong enrollment tokens fail; pending workers cannot serve requests before approval.
4. Add desk, then m5. Verify staging, bounded dynamic gRPC, worker readiness and restart recovery. Check GPU/GTT readings against host tools.
5. Install one model per node and pin placement. Exercise tool calls, streaming, cancellation and overlapping requests from two users. Confirm actual responding node.
6. Confirm the second user cannot administer models, nodes, secrets or another user's data.
7. Add local OIDC and HTTPS; test first login, logout, group/role handling and the recovery account.
8. Take a backup and restore into a fresh project. Verify accounts, existing API keys, model configuration, files and worker re-registration, then reload an archived model.
9. Capture pinned artifacts and benchmark results; test an upgrade and rollback against DB migration and backend changes.

## Primary references

- [LocalAI v4.11.0 release](https://github.com/mudler/LocalAI/releases/tag/v4.11.0)
- [Distributed mode](https://localai.io/docs/features/distributed-mode/)
- [Authentication and authorization](https://localai.io/docs/features/authentication/)
- [Model gallery](https://localai.io/docs/features/model-gallery/)
- [GPU acceleration](https://localai.io/docs/features/gpu-acceleration/)
- [NATS configuration](https://docs.nats.io/running-a-nats-service/configuration)
- [Docker Compose port publishing](https://docs.docker.com/reference/compose-file/services/#ports)
