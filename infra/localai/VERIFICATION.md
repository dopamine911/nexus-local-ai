# Verification record

Date: 2026-10-12. Working directory: `/home/daniel/dopamine911/repo/nexus-local-ai`.

## Completed

- Downloaded and inspected the public LocalAI v4.11.0 release source, including controller flags, worker configuration, role assignment, healthcheck, NATS connection, and upstream distributed Compose example.
- Queried Docker Hub registry manifests directly and pinned controller, Vulkan worker, PostgreSQL 17, and NATS 2 content digests in images.env. Registry manifest availability is not a container startup test.
- Ran 16 passing Python stdlib lifecycle tests, including actual Docker Compose rendering for both roles. Tests cover credential preservation and permissions, incomplete-state reinitialization refusal, admin bootstrap gating, private port publication, worker credential scope/advertisement, shell environment isolation, corruption checks, archive traversal rejection, and fresh-target recovery guards.
- Temporarily bypassed IP validation and backup verification in isolated test processes; their regression tests failed as expected. No production code was modified by these mutation checks.
- Executed the real CLI initialization and quiet validation against an isolated `/tmp` state directory. No credentials printed; no containers started.
- Confirmed generated `.runtime/` credentials are ignored by Git.

Reproduce the offline checks:

```bash
python3 -m unittest discover -s infra/localai/tests -v
python3 -m py_compile infra/localai/lab.py infra/localai/tests/test_lab.py
```

The Compose tests invoke the real CLI without a daemon. External account-bootstrap HTTP responses are simulated; a real password/login round trip has not been exercised. Backup verification uses constructed archives and actual checksums; it does not establish PostgreSQL dump/restore compatibility.

## Not yet established

- Live controller/dependency container startup and PostgreSQL schema initialization.
- Actual admin registration, worker enrollment/approval, authenticated NATS, GPU visibility, dynamic gRPC connectivity, or model inference.
- OIDC/HTTPS integration, tailnet access policy, and network isolation on the hardware.
- A complete database/file backup and restore drill, including existing API-key continuity and worker recovery.
- Runtime model/backend artifact pinning, encrypted NAS backup scheduling, performance, quality, and two-user contention.

The normal sandbox could not access the Docker daemon socket. This task prepared and tested the package without launching the homelab services. Host acceptance steps are listed in RESEARCH.md; unresolved work is explicit rather than counted as verified.
