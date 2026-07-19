# 0005. Remote access via Tailscale Serve; services stay bound to 127.0.0.1

**Status:** accepted
**Date:** 2026-07-18
**Supersedes:** —
**Superseded by:** —
**Related:** 0001 (host-only, isolated stacks), 0002 (keeping data local)

## Context

TheRig's stacks need to be reachable from a phone and laptop away from home
(point-of-decision budgeting only works if the app is in your pocket at the
store). The obvious way to make a service remotely reachable is to bind it to
`0.0.0.0` and open a port, but that exposes it to the LAN and — with a port
forward — the public internet. Docker makes this worse: published ports bypass
UFW, so a `-p PORT:...` mapping silently exposes a service to `0.0.0.0` even with
a host firewall configured.

TheRig already runs on a Tailscale tailnet. Tailscale Serve can proxy tailnet
traffic to a localhost port without the service ever binding beyond loopback.

## Decision

Remote access is via **Tailscale Serve only**. Every service stays **bound to
`127.0.0.1`**; Tailscale reaches it by proxying to that loopback port, not by
rebinding it to a public interface. Docker ports are published as
`-p 127.0.0.1:PORT:...`, never bare `-p PORT:...`. No service is exposed to the
LAN or the public internet.

## Consequences

- Services are reachable from authorized tailnet devices without any loopback
  service being exposed to the LAN or internet.
- Publishing a Docker port to `0.0.0.0` is the single biggest leak risk and is
  called out as such in the standing constraints; compose files must pin the
  `127.0.0.1` host.
- Access control rides on Tailscale's identity model rather than a hand-rolled
  network ACL.
- No inbound firewall holes to manage; the attack surface is the tailnet, not
  the open internet.
