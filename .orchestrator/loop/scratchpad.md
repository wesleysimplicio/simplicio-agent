---
iteration: 3
max_iterations: 20
completion_promise: null
evidence_required: true
mode: drain
started_at: "2026-07-12T22:57:00Z"
---

## Backlog (survey done — 11 targets from inventory, iteration 1)

- [x] 1. MCP server `hermes-tools` -> `simplicio-tools` (agent/transports/hermes_tools_mcp_server.py,
      hermes_cli/codex_runtime_plugin_migration.py, codex_runtime_switch.py,
      agent/transports/codex_app_server_session.py + legacy-name compat). Tests: 165/165 pass.
- [x] 2. Health/process identity: gateway/platforms/api_server.py `/health`,`/health/detailed`,
      `/v1/capabilities` "platform" field -> "simplicio-agent"; gateway/status.py `_GATEWAY_KIND`
      -> "simplicio-gateway" (+ `_LEGACY_GATEWAY_KIND` compat, both accepted by
      `_record_looks_like_gateway`); hermes_cli/main.py process title -> "simplicio-agent".
      Deliberately NOT touched: `_resolve_model_name`/`/v1/models` "id"/"model" field (client-facing
      routing key, needs its own alias-compat design) and systemd unit name
      "hermes-gateway.service" (separate, much larger surface — real installed services on user
      machines). Tests: 580/580 pass (2 pre-existing unrelated sandbox failures excluded,
      confirmed via git stash on unmodified code).
- [x] 3. Support bundle: hermes_cli/debug.py User-Agent -> "simplicio-agent/debug-share" (3x),
      MIME boundary -> "----SimplicioDebugBoundary9f3c". Deliberately NOT touched:
      `_NOUS_BUNDLE_FORMAT = "hermes-debug-share/1"` — cross-repo wire contract with the
      discord-support viewer (separate repo), renaming it is a breaking schema-version bump
      needing coordinated upcaster/dual-accept, not a same-repo string swap; left a comment
      explaining the decision. Tests: 91/91 pass.
- [x] 4. Telemetry/savings report titles + `prog=`: "Hermes Turbo" -> "Simplicio Turbo" in
      savings_report.py/gain_analytics.py; `prog=` hermes-savings-report/hermes-token-savings ->
      simplicio-*; dashboard.py description -> "Simplicio runtime telemetry dashboard". Tests:
      49/50 pass (1 pre-existing unrelated failure, test_perf_integration_manifest.py serde/msgspec
      env issue, confirmed via git stash).
- [x] 5. ACP client: agent/copilot_acp_client.py `clientInfo.name/title` -> "simplicio-agent"/
      "Simplicio Agent" (our own outbound identity to the Copilot ACP subprocess). Deliberately
      NOT touched: acp_registry/agent.json — tests/acp/test_registry_manifest.py pins it to the
      real external Nous Research ACP registry contract (id/name/repository/website asserted
      verbatim as "official registry required fields"); renaming would desync from that live
      external registry, not a same-repo cosmetic change. Tests: 31/31 pass.
- [x] 6. User-Agent literal sweep (delegated to a sub-agent with explicit keep/rename rules):
      36 production files renamed (HermesAgent/Hermes-Agent/hermes-agent/Hermes-Watcher outbound
      identity strings -> Simplicio equivalents; internal names, PyPI package "hermes-agent",
      GitHub URLs, `_NOUS_BUNDLE_FORMAT`, systemd unit name, `/v1/models` id all deliberately left
      untouched, consistent with items 1-5); 10 test files updated to match. Verified via targeted
      suites (~900 tests). One 3-test failure only reproduces when run in the same process as
      unrelated suites (confirmed via git stash: identical on unmodified code — pre-existing
      test-order pollution, not a regression).
- [x] 7. cli.py exception-path branding fallbacks (6 occurrences, more than the 3 originally
      spotted: lines 5537/5540/11888/12250/12254 "⚕ Hermes" -> "⚕ Simplicio", line 13569
      "Hermes Agent" -> "Simplicio Agent"), now consistent with the existing default at
      cli.py:3251. Deliberately NOT touched: the actual skin_engine default `agent_name` branding
      (still legitimately "Hermes Agent" — tests/hermes_cli/test_skin_engine.py pins it, and
      dozens of tests across the suite assert "Hermes Agent" appears in prompts/notifications;
      that's the human-facing product rebrand, a separate much larger piece of work, not #191's
      machine-identity scope — only the rare skin-load-failure fallback was in scope here).
      Verified: cli.py compiles; skin_engine test failures (5) confirmed pre-existing via git
      stash, none related to my 6-line edit.
- [ ] (no code target found) Schema ID/event_source/product_id versioning policy — issue's
      schema-versioning ACs have no existing schema_id/event_source field to version yet;
      likely needs a new module, treat as a separate design task, not a rename.

Issue #191 — [P0][Rename] MCP, schemas, telemetry, receipts e machine identities públicas
https://github.com/wesleysimplicio/simplicio-agent/issues/191

Nota de execução (esta run): os scripts do protocolo simplicio-loop
(task_backlog.py, loop_journal.py, watcher_verify.py, task_anchor.py,
impact_audit.py, flow_audit.py) NÃO existem nesta instalação — apenas a
documentação em references/. Operadores reais confirmados: simplicio-mapper
0.19.0 e simplicio-dev-cli (pip simplicio-cli). Loop conduzido manualmente
(scratchpad + git/gh como fonte de verdade), seguindo o espírito do contrato:
triagem -> decisão -> edição via simplicio-dev-cli -> teste como evidência.

Escopo (verbatim do issue): MCP server metadata/tool descriptions; JSON-RPC
product info; schemas/event source/product IDs; telemetry/savings/evidence
fields; support bundle; logs públicos; user-agent; update/release manifests;
process/health identities. Product identity = Simplicio Agent; Runtime
identity permanece Simplicio Runtime.
