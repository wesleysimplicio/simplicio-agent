# File-touch matrix — canonical-consumer rename (from simplicio-mapper #209)

When renaming the canonical consumer from `hermes` -> `simplicio-agent` (Simplicio Agent),
these are the exact spots that change. Adapt names per issue.

## Entry points (add canonical, deprecate old — keep old functional)
- `bin/cli.js`
  - CLI options list: add `{ key: 'simplicio-agent', label: 'Simplicio Agent (canonical consumer of the mapper)', cmd: 'simplicio-agent' }`
  - `handoff()` switch: `case 'simplicio-agent': requireCmd('simplicio-agent', '<repo url>')`
  - deprecation helper: `warnDeprecatedAlias(legacy, canonical)` guarded by `global.__simplicio_deprecation_warned`, writes to STDERR only
  - `case 'hermes':` calls `warnDeprecatedAlias('hermes','simplicio-agent')` then delegates
  - `printHelp` / `--cli` usage line: list `simplicio-agent`, note `hermes` is deprecated alias
- `bootstrap.sh`
  - CLI menu list: add `simplicio-agent|Simplicio Agent (canonical consumer of the mapper)|simplicio-agent`
  - `hermes)` case: `echo "[deprecated] ..." >&2` then retains fallback + `exec hermes "$INIT_PROMPT"`
- `bootstrap.ps1`
  - menu: `@{ Key="simplicio-agent"; Label="..."; Cmd="simplicio-agent" }`
  - `hermes` case: `Write-Warning "[deprecated] ..."` then `Require-Cmd` + `& hermes`
- `package.json`
  - `description`: name Simplicio Agent as canonical consumer
  - `keywords`: add `"simplicio-agent"` BEFORE `"hermes"` (keep hermes for discoverability)

## Docs (name canonical; mark old deprecated alias)
- `README.md` + `README.pt-BR.md`: intro description, `--cli <key>` table row, supported-CLI table (renumber rows after insert)
- `INIT.md` + `INIT.en.md`: compatible-CLIs line -> Simplicio Agent canonical, Hermes deprecated alias
- `AGENTS.md` + `CLAUDE.md`: "Master instruction file lido por ..." line + ".agents customizados ..." line
- `.agents/README.md`, `.agents/ralph-loop.agent.md`, `.github/copilot/agents/ralph-loop.agent.md`: agent lists
- `.specs/product/VISION.md`: problem-statement agent list

## Generated (regen, don't hand-edit the output)
- `docs-site/docs/reference/cli-flags.md` <- extracted from `README.md` (run `node scripts/sync-docs-site.mjs`)
- `docs-site/docs/reference/init-handoff.md` <- from `INIT.en.md` (same sync)
- `video/src/why/i18n.ts` (pt-BR + en `multiAgent.sub`) + `video/src/why/scenes/MultiAgent.tsx` (`AGENTS` orbit array)

## PRESERVE — do NOT edit (invariants 5/6)
- `contracts/ecosystem/v1/fixtures/asolaria-ecosystem/*.json` (ecosystem-graph.json, canvas-flow.json)
- `YOOL_TUPLE_HAMT.md` (Victor "Dev Hermes" Genaro attribution)
- `docs/*asolaria*` evidence/canvas docs
- `docs-site/versioned_docs/**` (frozen historical releases)
