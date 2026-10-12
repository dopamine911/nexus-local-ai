# Architecture proposal and review

Status: architecture draft, 2026-10-12. Controller and supporting infrastructure packages are now in [infra](../infra/README.md). The platform has passed isolated container bootstrap/recovery checks; no services are deployed on the lab hardware and no hardware benchmarks have run. Component choices remain subject to hardware acceptance.

## Direction

For two users and acceptable update downtime, use containerized services on two Linux hosts without a Kubernetes or high-availability requirement. Evaluate Ubuntu LTS first, with the exact host kernel, firmware, GPU driver, and container runtime selected from a tested AMD compatibility combination.

Machine 2 hosts infrastructure, routing, identities, dashboards, and supporting services. Machine 1 primarily serves larger local models. Machine 2's discrete GPU is shared between everyday inference, image generation, and training under an explicit scheduling policy; RAM/CPU headroom alone does not eliminate GPU contention.

Use Ansible for host preparation and Docker Compose for application deployment as the initial implementation candidates. Keep model manifests, non-secret settings, version pins, backup policy, and verification procedures in this repo. Do not promote copied shell snippets from reference plans directly into deployment code.

## Proposed applications

| Function | First candidate | Decision condition |
| --- | --- | --- |
| Model fleet, installs, settings, chat, API | LocalAI controller on Machine 2, worker on each AI host | Pilot actual R9700 and M5 workloads and two-user permissions before adopting |
| Local identities and SSO | Authentik on Machine 2 | Native OIDC where available; proxy protection where needed, with separate application authorization |
| Central landing page | Homarr on Machine 2 | Provide app links and supported status integrations; avoid a custom portal |
| Historical machine/GPU health | Beszel hub on Machine 2, agents on both | Verify actual utilization, temperature, power, and shared-memory readings on both devices |
| HTTPS and app routing | Caddy on Machine 2 | Select certificate/DNS method after domain and existing network discovery |
| Shared memory/knowledge | Evaluate LocalRecall and Basic Memory | Choose based on actual clients, per-user isolation, project collections, export, and restore tests |
| Experimental inference | Strata in a separate pinned container/profile | Benchmark against baseline serving before exposing a stable model alias |
| Image generation | Evaluate ComfyUI as an optional GPU service | Validate the chosen AMD/PyTorch workflow and scheduling against inference |
| Fine-tuning | Separate pinned ROCm/PyTorch training profile | Select training framework only after model family, adapter/full training, and data scope are known |
| Research search and ingestion | Evaluate a search service plus document extraction | Select after research sources are known; include local embeddings and citations |

LocalAI's distributed mode uses PostgreSQL for authentication/state and NATS for coordination. Its documentation describes node placement and centralized management. LocalAI also documents OIDC and an external-provider passthrough backend that can target OpenRouter-compatible APIs. Test these capabilities in the pinned release; do not add LiteLLM by default unless a measured requirement remains unmet.

LocalAI's UI does not replace historical GPU telemetry: its documented operations views omit temperature/power and keep some readings only while the page is open. Beszel fills that separate need. Open WebUI is an alternative chat front end if LocalAI's built-in interface proves insufficient; avoid deploying both initially just for overlapping chat functions.

Sources: [LocalAI distributed mode](https://localai.io/docs/features/distributed-mode/), [authentication](https://localai.io/docs/features/authentication/), [external-provider proxy](https://localai.io/docs/features/cloud-proxy/), [operations](https://localai.io/docs/operations/index.print.html), [Beszel GPU monitoring](https://beszel.dev/guide/gpu), [Homarr SSO](https://homarr.dev/docs/advanced/single-sign-on/), [Authentik forward authentication](https://docs.goauthentik.io/add-secure-apps/providers/proxy/forward_auth).

## Model entrypoint and task tiers

Use one stable local API endpoint with explicit aliases such as `coding-fast`, `coding-balanced`, `coding-deep`, `research`, and `embeddings`. Choose alias targets from measured model/quantization/context profiles rather than promising fixed performance or a universal automatic quality classifier.

Start with local-only fallback chains. Add explicitly labelled OpenRouter options only if configured and budgeted. Larger/deeper profiles may queue while a worker is occupied. Test overlapping requests from both users, long coding contexts, streaming, cancellation, and tool calls.

Image/training work needs its own scheduling and capacity reservations; an inference router cannot automatically manage arbitrary training processes. Retain independent SSH/Tailscale administration when the hub is down.

## Subscription access

Treat occasional Codex and Claude Code use through official subscription-authenticated tools as an explicit workflow alongside the local model API. Do not promise that subscription credentials act as generic router API keys or enable automatic free cloud fallback.

OpenAI documents separate ChatGPT subscription and API authentication for Codex. Anthropic describes subscription use in native applications and Claude Code; certain permitted third-party use may draw paid usage credits instead of subscription allowances. The implementation must preserve the user's preference against direct metered OpenAI/Anthropic API usage.

No second user's requests should be silently charged to or executed through the power user's subscription. Keep cloud account login separate from homelab SSO. OpenRouter remains a separately budgeted API option from the original goals.

Sources: [OpenAI authentication](https://learn.chatgpt.com/docs/auth), [Anthropic subscription authentication](https://support.claude.com/en/articles/13189465-log-in-to-your-claude-account).

## Memory design

Separate personal preferences, shared project knowledge, and research-document retrieval. They have different access and retention needs. Central storage does not cause every client to read or update it automatically; verify each client integration.

Basic Memory is a candidate for inspectable Markdown knowledge through MCP. LocalRecall is a candidate for a local knowledge/memory API and web interface. Prototype one representative coding workflow and one research workflow before choosing either. Do not deploy several overlapping memory systems by default.

Require private user namespaces, explicit shared collections, source provenance, deletion/export, and a tested restore. Verify the selected software can enforce those boundaries; separate instances are an acceptable fallback for two users. Keep memory data out of the infrastructure Git repository unless deliberately shared there.

Sources: [Basic Memory](https://github.com/basicmachines-co/basic-memory), [LocalRecall](https://github.com/mudler/LocalRecall).

## Strata assessment

Strata is an inference-engine candidate, not the shared-memory layer. Its README describes local OpenAI/Anthropic-compatible serving and lists the Radeon AI PRO R9700. Its Strix Halo documentation explicitly marks that path experimental and describes a source build on a maintainer's machine. Neither establishes performance on this user's systems.

Evaluate it as an optional backend using a pinned revision and repeatable build. Compare identical model artifacts where supported, context, tool-call behavior, quality, cold-load time, and memory headroom against the baseline. Any passthrough integration with the main API needs its own verification; do not assume managed-worker support.

Sources: [Strata](https://github.com/Niko1221/Strata), [Strix Halo support](https://github.com/Niko1221/Strata/blob/main/docs/STRIX_HALO.md).

## Review of Claude's reference plans

Reviewed all four Markdown files under `.local/plans`. Their main strengths are separating the infrastructure host from the larger-model worker, considering model-lifecycle management, acknowledging LocalAI's additional dependencies, and testing Vulkan versus ROCm.

Changes needed before adopting them:

- Treat performance figures, model rankings, flags, and release-specific environment variables as candidates to revalidate. A small benchmark run with differing engines and quants does not establish reliable model superiority.
- Reserve measured OS and runtime headroom on the M5. A GPU-accessible memory limit near total system RAM is not a safe model budget.
- Keep IOMMU enabled initially. Any tuning that disables it must be an explicit benchmarked experiment, not a default copied from a community recipe.
- Remove the assumed simple second-R9700 upgrade. The listed B550I board has one physical PCIe x16 slot; a second card would require a separately designed hardware change, riser arrangement, or platform upgrade.
- Replace the custom model-control page with maintained interfaces where practical, and enforce separate normal-user versus administrator privileges.
- Add local SSO, persistent memory, image/training scheduling, secrets lifecycle, database-consistent backups, independent backup copies, and restore drills.
- Pin downloaded backends and artifacts as well as top-level container images. Image-tag rollback alone may not reverse database migrations or mutable runtime downloads.
- Benchmark direct LAN versus Tailscale host-to-host transfers and choose the internal service path deliberately. Remote user access remains through Tailscale.

Source for the expansion-slot constraint: [Gigabyte B550I AORUS PRO AX specifications](https://www.gigabyte.com/pt/Motherboard/B550I-AORUS-PRO-AX-rev-10/sp). Confirm the actual board revision during hardware inventory.

## Delivery sequence

1. Finish network/NAS inventory, model-workload scope, and memory-client discovery.
2. Capture host build recipes and test GPU access from pinned containers on each machine.
3. Pilot one ordinary and one larger coding model, then benchmark tool calls, context, and two-user concurrency.
4. Validate LocalAI worker placement, model installs/settings, restart behavior, artifact pinning, and a standalone recovery path.
5. Add SSO, the landing page, health history, and user-specific API credentials.
6. Prove backup/restore and upgrade rollback before treating the stack as the daily default.
7. Add memory and research integration, then image generation and adapter-training experiments.
8. Test Strata as an optional serving profile and publish measured model recommendations.

Open items are tracked in Requirements.md. This discovery draft does not validate or install any component.

The controller pilot implementation and source research now live in [infra/localai](../infra/localai/README.md). Its verification record distinguishes offline checks from host acceptance; the overall architecture remains provisional.
