---
name: simplicio-mapper-contracts
description: Add or evolve JSON-Schema contracts, fixtures, wheel/sdist packaging and clean-install validation for the simplicio-mapper repo (canonical observer/artifact envelopes like ContextSnapshot/ContextGraph). Trigger when touching contracts/*, simplicio_mapper/contract.py, or shipping a new artifact schema that must validate on a clean pip install.
trigger:
  - criar nova familia de schema em contracts
  - editar o validador nativo simplicio_mapper/contract.py
  - exigir que schemas validem em clean install (wheel/sdist)
  - trabalho estilo issue 208 (envelope observer/artifact content-addressed)
steps:
  - Definir schema id estavel e discriminador schema como enum (NUNCA const).
  - Espelhar o layout de contracts/mapper-artifacts/v1 schemas fixtures README.
  - Registrar o schema id em SCHEMA_FILENAMES e resolver dir de schemas com fallback repo.
  - Empacotar no wheel e sdist via force-include no pyproject.
  - Gerar fixtures latest (run real) e minimum (tiny, para Rust).
  - Escrever testes unittest.TestCase validando fixtures e id content-addressed.
  - Verificar ruff, unittest discover, wheel build, clean-install validate.
pitfalls:
  - contract.py native validator NAO suporta JSON Schema const. Use enum.
  - Schemas NAO sao empacotados por padrao. Force-include no pyproject.
  - Testes Python devem ser classes unittest.TestCase; discover ignora funcoes soltas.
  - ruff E702 em tuplas de comandos; rode ruff format apos editar _args.py.
  - snapshot_id content-addressed hashea body menos campos volateis.
  - Provar falha pre-existente: git diff main...HEAD --name-only.
dod:
  - ruff clean nos alterados; slice e test_contract verdes; CLI e2e ok; wheel inclui contracts; clean-install errors=[]; PR com evidencia.
---
# simplicio-mapper-contracts

Class-level skill for adding or evolving JSON-Schema contracts, fixtures,
wheel/sdist packaging, and clean-install validation in the `simplicio-mapper`
repo. Covers the canonical observer/artifact envelope pattern introduced by
issue #208 (ContextSnapshot / ContextGraph) and any future contract family.

## When to use
- Creating a new schema family under `contracts/<family>/v1/schemas`.
- Editing the native validator `simplicio_mapper/contract.py`.
- An AC requires a clean `pip install simplicio-mapper` to validate an
  artifact (schemas must ship in wheel + sdist).
- Any content-addressed / versioned / fidelity-proven artifact envelope.

## Workflow (summary)
See `steps` in frontmatter. Full reproduction recipes for every gotcha live
in `references/mapper-contract-gotchas.md`.

## Pitfalls (condensed)
1. No `const` in contract.py validator — emit `{"enum":["simplicio.x/v1"]}`.
2. Schemas are not packaged by default — force-include in `pyproject.toml`
   and resolve from `simplicio_mapper/contracts/<family>` with repo-source fallback.
3. Python tests must be `unittest.TestCase` subclasses — bare functions are
   silently skipped by `discover` ("Ran 0 tests").
4. ruff E702 on command tuples — run `ruff format` after editing `_args.py`.
5. Content-addressed id — hash body minus volatile fields, compact separators
   (`sort_keys=True, separators=(",",":")`, `ensure_ascii=False`).
6. Pre-existing failure vs regression — `git diff main...HEAD --name-only`
   proves the failing file is outside your diff; optionally run the failing
   test against the pristine `main` version of the test file.

## DoD
ruff clean on changed files · slice + `test_contract.py` green · CLI e2e
`build`+`validate` -> `[ok]` · wheel includes `simplicio_mapper/contracts/<family>/...`
· clean-install validation `errors=[]` · PR with AC checklist + real evidence.
