# Ecosystem invariants to preserve during a rebrand (simplicio-mapper #209)

These held the mapper rebrand honest. Reuse the shape for any ecosystem rename.

1. **Own identity preserved.** The repo keeps its package name (simplicio-mapper stays
   simplicio-mapper). It is the OBSERVER/PRODUCER of `ContextSnapshot`, not the consumer.
2. **Canonical consumer = Simplicio Agent** (`simplicio-agent`). The mapper points to it
   as the canonical reader/integrator.
3. **Bootstrap does NOT install upstream Hermes.** `hermes` remains a deprecated alias only.
4. **JSON / stdout stay parseable via the alias.** Any `simplicio.*` schema IDs in
   `contracts/mapper-artifacts/` are canonical and untouched (no `hermes` in schema IDs).
5. **Upstream Asolaria fixtures preserved.** `contracts/ecosystem/v1/fixtures/asolaria-ecosystem/*`
   and the YOOL Victor "Dev Hermes" Genaro attribution are upstream/attribution data — byte-preserve.
6. **Standalone works without the Agent.** Mapper runs, maps, emits artifacts with no
   Simplicio Agent present. The rebrand only changes WHICH consumer is recommended.
7. **Versioned docs are historical.** `docs-site/versioned_docs/**` are frozen release
   snapshots — regenerate only `docs-site/docs/` via the sync script; never rewrite history.

Cross-repo release DAG (Wesley's correlated-release order): mapper FIRST, then
simplicio-dev-cli, then simplicio-loop. An umbrella rename issue closes only after all
three apply the same canonical-consumer change and the ecosystem release gate is proven.
