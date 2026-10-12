# Network plan — draft

Research date: 2026-10-12. USD prices observed on vendor sites, before tax/shipping; recheck before purchase. No hardware selected or purchased.

## Proposed topology

```text
Internet
   |
Existing router/firewall (model and VLAN support TBD)
   |
Managed switch
   +-- Machine 1: Bosgame M5, target 2.5GbE
   +-- Machine 2: infrastructure + GPU workloads, target 2.5GbE
   +-- Unraid NAS: target 2.5GbE initially; optional 10GbE later
   +-- Workstation / existing switch / spare ports
```

An eight-port switch leaves expansion room after the router, two AI hosts, and NAS are connected. Host-to-NAS traffic on the same VLAN stays on the switch, so a 1GbE router uplink does not cap those transfers. Inter-VLAN traffic depends on router throughput and uplink capacity.

Use existing sound Cat5e cabling where suitable; use Cat6 for new short runs. Start with MTU 1500 and test link negotiation and throughput. Do not assume jumbo frames or link aggregation are needed.

Run Tailscale directly on both Linux hosts to preserve access when Machine 2's application stack is unavailable. Decide NAS participation and access policy during deployment planning. Remote administrative and application access should use the tailnet without public dashboard port forwards.

## Switch shortlist

| Model | Ports | Observed price | Fit |
| --- | --- | --- | --- |
| Zyxel XMG1915-10E | 8 x 2.5GbE RJ45 + 2 x 10GbE SFP+ | $199.99 on Zyxel US store | Preferred candidate if budget permits; standalone web management and future faster NAS uplink |
| NETGEAR MS108EUP | 8 x 2.5GbE RJ45 with PoE+/PoE++ | $309.99 on NETGEAR US site | Consider if powering access points/cameras is a requirement; extra cost offers little value for just the three servers |
| TP-Link TL-SG108E | 8 x 1GbE RJ45 | Current US price not verified | Budget fallback with web management and VLAN support; verify hardware revision and firmware support before buying |

SFP+ ports require a compatible NIC and DAC/optics; those costs are additional. Buying the Zyxel does not itself give the NAS a 10GbE connection.

Sources:
- [Zyxel specifications, standalone management, and price](https://store.zyxel.com/xmg1915-10e-us0101f.html?___store=us_en_storeview)
- [NETGEAR specifications and price](https://www.netgear.com/business/wired/switches/easy-smart/ms108eup/)
- [TP-Link TL-SG108E specifications](https://www.tp-link.com/us/business-networking/easy-smart-switch/tl-sg108e/)

## Logical network

Reserve stable addresses/names through router DHCP reservations. Choose subnets after checking the existing LAN and VPN routes to avoid overlap.

If the router supports VLANs and firewall rules, consider a lab VLAN for the AI hosts and NAS, with management access limited to trusted clients and the tailnet. Additional management/storage VLANs are optional and should serve a concrete isolation need.

A VLAN-capable switch alone cannot supply the router's inter-VLAN firewall policy. If the existing router lacks support, start on the existing LAN with host firewalls and Tailscale, then evaluate a separate firewall upgrade.

## Storage and throughput

2.5GbE has a theoretical line-rate ceiling of 312.5 MB/s; application throughput is lower and disks may dominate. It is a reasonable initial target for model transfers, datasets, and backups with local NVMe caches. Do not plan distributed GPU training or split-model inference across these hosts without separate benchmarking.

Using the user-reported disk capacities:
- One 23 TB parity disk + 23/12/12 TB data disks: approximately 47 TB decimal data capacity before filesystem overhead.
- Two 23 TB parity disks + 12/12 TB data disks: approximately 24 TB decimal data capacity before filesystem overhead.

Both layouts satisfy the parity-size rule if the reported capacities are accurate. Choose after considering data value, capacity requirements, and independent backups. Confirm exact drive labels before calculating the final layout. Evaluate an SSD cache pool for NAS write performance; active application state remains local to the AI hosts in this draft.

Source: [Unraid array and parity rules](https://docs.unraid.net/unraid-os/using-unraid-to/manage-storage/array/overview/).

## Validation before acceptance

- Confirm NICs, negotiated speed, and switch firmware.
- Measure host-to-host and host-to-NAS throughput, then representative model/dataset transfers.
- Verify allowed and denied access from LAN and Tailscale clients.
- Verify remote host administration survives an application-stack outage on Machine 2.
- Export switch configuration and document recovery, including manually applied settings where automation is unavailable.
