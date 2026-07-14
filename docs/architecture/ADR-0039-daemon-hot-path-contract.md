# ADR-0039: Bounded daemon hot-path contract

- Status: bounded contract
- Date: 2026-07-14
- Related: issue #319, ADR-0038

## Decision

`tools/daemon_hot_path.py` freezes a small, versioned boundary around the
current warm-daemon and `AgentHost` interfaces. It covers startup intent,
health classification, bounded reconnect decisions, worker crash isolation,
and a protocol-compatible rollback plan. The module is pure: it does not own
processes, sockets, schedulers, providers, activation, or rollback side
effects.

The current Python daemon may shadow-run these decisions. A response without a
protocol version is explicitly `unreported` and is not native-ready; an
incompatible version fails closed. Reconnect attempts and delays are bounded,
and worker exceptions become a stable secret-free cold-path receipt. Rollback
is allowed only when a distinct previous version exists and its protocol is
compatible.

## Wire contract

The schema is `simplicio.agent-daemon-hot-path/v1`. Startup carries
`profile`, `protocol_version`, and `generation`. Health projects the existing
`ok`, `profile`, optional `host.ready`/`host.stopping`, and the new version
field without exposing filesystem paths, provider details, or exception text.

`fixtures/native/daemon_hot_path_contract.json` is the golden input/output
fixture for a future compiled implementation. `tests/tools/test_daemon_hot_path.py`
covers protocol failure, health, reconnect bounds, crash isolation, stop and
rollback transitions, and JSON stability.

## Evidence boundary

This slice proves the deterministic Python contract only. A compiled Rust
daemon binary, p50/p95 hot-path measurements, clean-machine installation, and
live rollback are `UNVERIFIED|` until a runtime build and evidence-producing
process gate exist. No production claim is made by this module or fixture.
