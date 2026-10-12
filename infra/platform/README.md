# Machine 2 platform

Off-the-shelf services with repository-managed Compose configuration and Python stdlib lifecycle scripts. Images are selected by registry digest in `images.env`; no service receives the Docker socket.

| Component | URL with the placeholder | Access / state |
| --- | --- | --- |
| Homarr | `https://lab.home.arpa` | Portal; native OIDC after bootstrap; encrypted integration settings |
| Authentik | `https://auth.lab.home.arpa` | Identity provider; PostgreSQL + persistent `/data`; automatic application blueprint |
| LocalAI | `https://ai.lab.home.arpa` | Existing controller; native OIDC and authenticated OpenAI-compatible API |
| Beszel | `https://health.lab.home.arpa` | Historical host/GPU metrics; native OIDC configured during setup |
| SearxNG | `https://search.lab.home.arpa` | Optional `research` profile; Authentik forward authentication |
| ComfyUI | `https://images.lab.home.arpa` | Separate workload package; Authentik power-user group only |
| Basic Memory | MCP stdio, no web port | Optional power-user Markdown memory; separate from chat history |

## Bootstrap

Run on machine 2 as the deployment operator with Docker Compose and Python 3.12+. Replace the sample email and private IP. Runtime state can be under `/srv/nexus` or an ignored `.runtime` directory; never store it in tracked files.

```bash
python3 infra/platform/stack.py --state-dir /srv/nexus/platform init --admin-email you@example.net
python3 infra/platform/stack.py --state-dir /srv/nexus/platform validate
python3 infra/platform/stack.py --state-dir /srv/nexus/platform up
python3 infra/platform/stack.py --state-dir /srv/nexus/platform export-ca
python3 infra/platform/stack.py --state-dir /srv/nexus/platform restart
```

Initialization binds Caddy to **127.0.0.1** and generates independent secrets. Read the Authentik `AUTH_BOOTSTRAP_PASSWORD` from the private state `.env` in your password manager/editor; login is `akadmin`. This password bootstraps once, not on every restart. Rotate it in Authentik after recording a recovery credential.

On a headless server, use an SSH tunnel such as `ssh -L 8443:127.0.0.1:443 operator@machine2`. Temporarily resolve the placeholder hostnames to localhost on the client and open `https://lab.home.arpa:8443` and `https://health.lab.home.arpa:8443` to create the initial Homarr and Beszel administrator accounts. The IdP can be reached at `https://auth.lab.home.arpa:8443`; OIDC callbacks use standard 443 and are tested after publication. Verify the exported CA fingerprint over SSH before trusting `trust/root.crt` on the client. Initial browser certificate warnings are resolved by installing that CA; never disable TLS verification in clients.

In Authentik, check **Customization → Blueprints → Nexus applications** is successful. Create the occasional user explicitly and add it to `homelab-users`. Add the power user to both `homelab-users` and `homelab-admins`. The `akadmin` recovery identity has its own bindings. No public enrollment source is installed.

Create the initial portal board using `dashboard-links.json`. Homarr's onboarding/board format is deliberately not automated through an undocumented API. The board and permissions become persistent backed-up application state. In Homarr, create groups matching the IdP group names and assign administrator rights only to `homelab-admins`; verify ordinary users cannot edit integrations or boards. Native OIDC creates a separate identity unless the application supports an explicitly reviewed linking process; do not assume an existing credential account will be automatically linked.

## DNS, trust and publication

For `lab.home.arpa` and `auth`, `ai`, `health`, `search`, `images` subdomains, create DNS A records pointing to machine 2's Tailscale IPv4. MagicDNS alone does not create these arbitrary private-domain records. Use the LAN resolver with Tailscale split DNS or explicit client hosts records during the pilot. Keep the NAS resolver reachable by authorized tailnet users.

```bash
python3 infra/platform/stack.py --state-dir /srv/nexus/platform enable-oidc
python3 infra/platform/stack.py --state-dir /srv/nexus/platform publish --ip 100.100.10.12 --accounts-reviewed
python3 infra/platform/stack.py --state-dir /srv/nexus/platform up
python3 infra/platform/stack.py --state-dir /srv/nexus/platform connect-localai --controller-state /srv/nexus/localai-controller
python3 infra/localai/lab.py --state-dir /srv/nexus/localai-controller restart
```

`--accounts-reviewed` records **your assertion** that initial administrator accounts exist; it is not an automated login test. Publication allows the tailnet interface only. Tailnet ACL/grant policy must allow these two users HTTPS and restrict LocalAI control-plane ports to worker/operator nodes. Avoid router port forwarding. LocalAI's direct authenticated worker/control endpoint remains required; browser SSO does not substitute for worker enrollment or API keys.

The proxy's private CA persists in a named volume. `export-ca` exports only its public root and a public+private trust bundle. Homarr, Beszel and the connected LocalAI controller use that bundle. Re-export/restart after CA rotation, and replace client/agent trust only after verifying the new fingerprint. DNS aliases also let containers reach the same external issuer URL through Caddy.

### Beszel OIDC and accounts

Beszel's OIDC provider lives in its PocketBase `users` collection. Configure it through `https://health.lab.home.arpa/_/` using the [upstream integration procedure](https://integrations.goauthentik.io/monitoring/beszel/). Provider client ID is `beszel`; secret is `BESZEL_OIDC_SECRET` in private `.env`. URLs:

```text
Authorization: https://auth.lab.home.arpa/application/o/authorize/
Token:         https://auth.lab.home.arpa/application/o/token/
User info:     https://auth.lab.home.arpa/application/o/userinfo/
Callback:      https://health.lab.home.arpa/api/oauth2-redirect
```

The blueprint's email mapping defaults to unverified. After you verify each curated user's email, set the Authentik user attribute `email_verified: true`; Beszel requires it. Pre-create the corresponding Beszel email identity, grant only needed systems, and give the occasional user the read-only role. Automatic user creation remains off. Keep a local recovery login until successful SSO/logout/role tests; PocketBase superuser recovery is a separate administrative account.

### Agents on both machines

Add each system in Beszel and obtain **its own** public SSH key/token. Copy `config/agent.credentials.example.json` to private host state, replace placeholders, and copy the exported public root certificate. Never commit the populated file.

```bash
python3 infra/platform/agent.py --state-dir /srv/nexus/health-agent init --credentials /srv/nexus/agent.credentials.json --ca /srv/nexus/root.crt
python3 infra/platform/agent.py --state-dir /srv/nexus/health-agent validate
python3 infra/platform/agent.py --state-dir /srv/nexus/health-agent up
```

Agents use host networking, bind to their explicit Tailscale IP on 45876, persist enrollment state, and read AMD sysfs metrics. Let only the hub reach that port. The hub can also receive outbound authenticated agent WebSockets through HTTPS. CPU/RAM/network and available sysfs GPU metrics are the baseline. Container logs/statistics and SMART are not enabled because they require more host privileges; verify disk metrics correspond to the host NVMe before adding alerts. Integrated GPU memory/utilization reporting depends on its kernel interfaces.

## Research and memory

```bash
python3 infra/platform/stack.py --state-dir /srv/nexus/platform research enable
python3 infra/platform/stack.py --state-dir /srv/nexus/platform up
```

SearxNG exposes HTML/JSON search with Valkey available as its key/value backend. Its bot limiter is disabled for this private two-user deployment so scripted research clients are accepted. Browser requests require the Authentik `homelab-users` binding. LocalAI containers can deliberately use `http://searxng:8080/search?format=json&q=...` on their private shared AI network; this is a machine API trust boundary. It is not published directly. Search contacts external search engines, so this profile is local orchestration with online research, not offline inference. Disabling it stops both services. Review rate limiting before adding more users or exposing a new machine endpoint.

Basic Memory is a **power-user** memory store, with both Markdown and its configuration/database persisted. Launch per MCP session:

```bash
docker compose -p nexus-platform --env-file /srv/nexus/platform/.env -f infra/platform/compose.yaml run --rm --no-deps -T memory
```

Configure that argv as a stdio MCP server for a client running on machine 2. Do not give the occasional user Docker access to reach it: Docker membership is effectively host administration. A remote client can use authorized SSH stdio transport for the power user. An independently isolated second-user memory service is required before sharing this feature. Stop MCP sessions before backup; the snapshot script rejects active memory writers. There is no exposed SSE/HTTP memory endpoint and no implicit merging of private memories.

## Operation and verification

Use `status`, `logs`, `down`, `up`, and `restart` commands. `down` preserves volumes. After changing tracked templates, run `sync-config` then `restart`; after image/environment changes, `up` recreates affected containers. [Operations](OPERATIONS.md) covers backups, recovery, upgrades and benchmarks. [Verification](VERIFICATION.md) distinguishes executed checks from hardware acceptance tests.

Primary references: [Authentik deployment](https://docs.goauthentik.io/install-config/install/docker-compose/), [Homarr OIDC](https://homarr.dev/docs/advanced/single-sign-on/), [Beszel agents](https://beszel.dev/guide/getting-started), [Beszel GPU metrics](https://beszel.dev/guide/gpu), [SearxNG containers](https://docs.searxng.org/admin/installation-docker.html), [Basic Memory](https://github.com/basicmachines-co/basic-memory).
