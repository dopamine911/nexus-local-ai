# Verification record — 2026-10-12

## Executed

* Python compile checks for controller, platform, agent, backup, benchmark and workload scripts.
* Controller tests: 16 passing. Platform/benchmark tests: 16 passing, including actual concurrent loopback HTTP requests. The HTTP fixture requires local socket permission when the execution sandbox denies sockets.
* Real Docker Compose rendering for platform, all optional profiles and GPU jobs: explicit private binding, no database/search/image/memory published ports, no Docker sockets, offline training, secret/profile shell-override prevention, persisted application state.
* Pinned Caddy image accepted the HTTPS/forward-auth configuration. A live TLS request to search without a session redirected to Authentik before reaching the search service.
* Pinned Authentik 2026.8.3 + PostgreSQL 17 bootstrapped in an isolated project. Generated blueprint validated/applied successfully and created Homarr, LocalAI, Beszel, search and image application/provider entries.
* Homarr served its HTTP onboarding page; Beszel's image health command passed. SearxNG served private HTTP after startup; its limiter is deliberately disabled to accept scripted private clients.
* Basic Memory 0.23.2 image started and completed a real stdio MCP initialize handshake against its persistent test volumes.
* Real platform backup and restore into a new project passed, including PostgreSQL state, Authentik media sentinel, application volumes and the private CA. The restored IdP served CA-verified HTTPS OIDC discovery with the expected Homarr issuer.
* Pinned restic initialized an encrypted repository, backed up the snapshot, passed `check --read-data`, restored it, and produced byte-identical files.
* Host provisioning playbook passed ansible-core 2.19.3 `--syntax-check`; no host provisioning was executed. Repository signing-key checksums and exact package versions were resolved from official repositories.
* Docker `build --check` accepted the ComfyUI Dockerfile; source archive checksum and Python package hashes are pinned. The lock excludes replacement torch/torchvision/triton and NVIDIA packages.

The backup drill uncovered Authentik's shipped `/data/media → /media` link. The implementation now persists `/media` independently and validates that exact compatibility link while rejecting traversal through it. Ordinary symlinks, hardlinks, path escapes, duplicate entries and corrupt manifests remain rejected. Guard mutations must fail their corresponding tests.

## Environment limitations observed

The verification engine was Docker Desktop 29.8.1 with Compose 5.5.1. `/tmp` bind mounts were outside its shared directories, so test configuration moved under ignored repository `.runtime`. Reading private snapshot files via a Desktop host bind produced I/O errors; the restic round trip therefore used streamed files in disposable Docker volumes. The production scripts target a native Linux Docker host and still require the real NAS mount/write/read/recovery test. They refuse absent mounts and retain staging on a failed upload.

An early smoke backup restart briefly recreated the proxy with loopback-only test ports; the no-port override was reapplied. No Tailscale or public lab endpoint was published. Test projects/volumes are removed after verification; downloaded test images remain cached.

## Required on the lab machines

* OS, kernel/firmware/amdgpu and both actual GPU tensor probes; M5 memory allocation/headroom and R9700 VRAM contention.
* Full ComfyUI image build/start, fixed workflow/model generation, and a selected/versioned fine-tuning recipe. Build checks do not prove runtime or GPU compatibility.
* Actual two-user browser SSO, logout, role restrictions, Beszel PocketBase OIDC setup, dashboard groups/board and recovery accounts. No end-to-end browser authorization-code login was asserted.
* Tailscale addresses/grants, DNS resolution and CA trust on both clients/hosts; host NVMe and available GPU metrics after agent enrollment.
* Real Unraid share permissions/mounting, backup timer installation, absent-NAS failure and clean-host recovery with externally held restic password.
* LocalAI controller-to-worker jobs through the proxy/network integration, model artifacts, request latency/quality measurements, online research results and image/training data recovery.
* Optional provider integration and model recommendations remain separate from hardware performance claims.
