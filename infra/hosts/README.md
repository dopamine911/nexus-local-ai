# Host bootstrap

`provision.yaml` prepares a **new Ubuntu 24.04 amd64 machine 2**, installs exact Docker/Tailscale package versions from official signed repositories, holds runtime packages for reviewed upgrades, starts their daemons and prepares private persistent state. Signing keys have SHA256 checksums recorded on 2026-10-12. It refuses conflicting container packages instead of removing an existing runtime.

Copy `inventory.example.yaml` into ignored private configuration and replace the host address and existing administrator username. Use an Ansible controller with ansible-core installed; preview using `--check --diff` where applicable, then apply on the actual host:

```bash
ansible-playbook -i .local/inventory.yaml infra/hosts/provision.yaml --ask-become-pass
```

The listed IP is a placeholder, not an assigned address. SSH reachability must already exist over LAN or an enrolled tailnet. The playbook installs Tailscale but does not enroll the machine, alter tailnet policy, change DNS, install the AMD driver, mount the NAS, install timers or reboot. Complete interactive `tailscale up` once on the machine and record node/tag policy in the private inventory/runbook; authentication keys stay out of Git. Log out/in for Docker group membership to apply.

The existing deployment operator receives Docker administration; the occasional user receives web/SSO access only. `/srv/nexus` is private to the power operator. Review Docker's port publishing behavior alongside tailnet policy: host firewall assumptions alone do not restrict published container ports.

Machine 1 needs its own distribution/driver decision. Do not run the Ubuntu playbook against Fedora or install a generic server ROCm stack onto the M5 without confirming support. A reproducible M5 host installer, pinned kernel/firmware and bare-metal OS installation remain a hardware acceptance phase. Container AMD runtimes still depend on the host kernel/driver.

For a future runtime upgrade, review the package pins and hold policy explicitly; Ansible package holds can block upgrades until deliberately changed. Archive required packages/images if upstream retention is a concern. Base Ubuntu utility packages are not a full immutable OS snapshot: keep the installed package/kernel manifest and OS installer version with recovery records.

Primary sources: [Docker Ubuntu installation](https://docs.docker.com/engine/install/ubuntu/), [Tailscale Linux installation](https://tailscale.com/docs/install/linux).
