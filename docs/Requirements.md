# Local AI homelab requirements

Updated: 2026-10-12. Planning stage; proposed implementations require compatibility validation.

## Confirmed goals

1. Track infrastructure design, configuration, and repeatable deployment scripts in this repository. Minimize undocumented one-off commands and support rebuilding from scratch.
2. Provide a convenient model-router entrypoint for local models and OpenRouter, with Codex and Claude account integration investigated separately for supported authentication and execution paths.
3. Provide machine and service health dashboards.
4. Manage models and runtime settings through web interfaces, with settings preserved through rebuilds.
5. Prefer maintained off-the-shelf software over custom applications.
6. Maintain model recommendations by task, including hardware fit, quantization, context limits, and measured results.
7. Evaluate supporting applications that improve the local stack.
8. Run infrastructure and supporting services on Machine 2. Model workloads may use either machine.
9. Support remote access through Tailscale.
10. Provide scheduled backups, retention, documented recovery, and tested restores.
11. Manage secrets outside plaintext Git history and back up recovery credentials securely.
12. Control upgrades, record compatible versions, and provide rollback procedures.
13. Run reproducible benchmarks for performance and task quality before promoting upgrades or model changes.

## Confirmed preferences and hardware

- Workloads: coding, research, some image generation, and fine-tuning.
- Linux hosts; Debian-based distributions preferred. Fedora is a candidate for the M5 if compatibility requires it.
- Containerized applications and GPU user-space environments preferred.
- Each AI machine has a 1 TB NVMe SSD; see Hardware.md.
- Separate Unraid NAS planned with 2 x 23 TB and 2 x 12 TB disks; exact models/capacities unverified.
- Existing small switch; seek affordable managed 1–2.5GbE networking.
- Two users: one power user and one occasional user. Concurrent workload count is still TBD.
- Provide selectable fast, balanced, and deeper/accuracy-oriented options; measure quality rather than assuming the largest model wins.
- Local-first operation. ChatGPT/Codex and Anthropic subscriptions are occasional cloud options; direct metered OpenAI/Anthropic APIs are not the desired integration.
- Prefer few web interfaces, local SSO, and a central landing dashboard when multiple applications are needed.
- This is a recreational homelab; planned downtime for upgrades is acceptable. High availability is not required.
- Evaluate persistent memory and other useful supporting applications, including Strata as an inference-engine candidate.
- Claude's previous proposals are in `.local/plans`; treat them as reference material, not validated deployment instructions.

## Proposed implementation principles

- Evaluate Ubuntu LTS on both AI hosts against the selected AMD driver/runtime matrix and actual machine tests before choosing final versions.
- Keep host kernel, firmware, and GPU-driver versions in the build inventory. Containers share the host kernel and cannot independently pin the GPU kernel driver.
- Evaluate Ansible for host configuration and Docker Compose for application deployment; no orchestration platform selected yet.
- Keep infrastructure services available while image generation or fine-tuning occupies a GPU. Plan resource limits and workload scheduling.
- Keep active model caches, databases, and training scratch on local NVMe. Use NAS storage for model archives, datasets, checkpoints, and versioned backups.
- Back up unique data preferentially; record checksums and download provenance for replaceable model weights.
- Include database-consistent backups, an independent copy of irreplaceable data, secret recovery, and restore tests. NAS parity alone is insufficient for this goal.
- Benchmark model quality, time to first token, prompt processing, generation speed, concurrency, peak memory, and power where measurable. Include representative coding/research tasks and training/image smoke tests.
- Keep private user memories separate. Shared project knowledge should be an explicit collection with controlled access.
- Propose explicit cloud selection with local-only fallback chains initially; the user has confirmed local-first but has not yet chosen automatic cloud-egress policy.
- Use each person's own provider account for subscription tools; a local SSO account does not grant another person's cloud subscription entitlement.

## Unresolved decisions

- Router and existing switch models, VLAN support, switch budget, and PoE needs.
- NAS platform, NIC, cache pool, drive models, parity layout, and independent backup destination.
- Concurrent job count, GPU scheduling expectations, and whether batch workloads may pause interactive model serving.
- Exact subscription tiers, acceptable supported integration surfaces, OpenRouter budget, and cloud-routing privacy rules.
- Primary coding clients, research sources, desired context lengths, and latency targets.
- Fine-tuning scope: text or image models, adapter training versus full tuning, model sizes, and datasets.
- Exact web-management controls and any existing local identity provider/domain/DNS setup.
- Scope and clients for central memory: coding-project knowledge, research documents, personal preferences, or all three.
- Any decisions already accepted from Claude's previous proposals.
