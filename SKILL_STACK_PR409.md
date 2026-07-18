# Pre-Implementation Gate Evidence — PR #409

**Issue domain:** adapter version floor for simplicio-loop preflight (mapper incompatibility 0.18.0 < min 0.19.0 blocked the loop).

**Gate #400 sequence (retroativo):**

### 1. Neural memory recall
- `simplicio memory "adapter version floor simplicio-loop preflight mapper incompatibilidade"` → **0 results**.
- Recorded explicitly: `UNVERIFIED| banco vazio` para este domínio.

### 2. Skill stack loaded (universal + scope)
- `simplicio-tasks` — body-of-work orchestration
- `simplicio-loop` — loop contract, DoD 7 dims, close-gate
- `simplicio-orient` — terminal-first execution, token economy
- `simplicio-review` — adversarial verify (n/a for docs-only change)
- `simplicio-learn` — retrospective lesson
- `simplicio-compress` — output reduction
- Scope additions:
  - `simplicio-runtime-evolution` — runtime/agent evolution
  - `github-pr-workflow` — PR handoff

### 3. Evidence (what was actually done)
- `simplicio doctor --json` (simplicio-agent): mapper 0.23.1 compatible, dev-cli 0.25.0, prompt 1.14.1, loop 3.35.0, runtime 3.5.2 — todas `compatible`.
- `simplicio-mapper scan .` over runtime: `phase: macro_done`, 5103 files, 0 errors.
- `simplicio contracts smoke --json`: `status: passed`.
- PR #409: `adapter-requirements.toml` documenting the version floor (12 lines, 1 file).

### 4. DoD gate (7 dimensions)
1. ✅ Implementação — manifest de piso de versão criado.
2. ⚠️ Testes unitários — N/A (docs-only TOML; no code path changed).
3. ⚠️ Testes de integração — N/A (manifest is declarative; consumed by `doctor` indirectly).
4. ✅ Testes de sistema — `doctor --json` + `contracts smoke` passam com o piso documentado.
5. ✅ Regressão — estado anterior (mapper 0.18 incompatível) reproduzido e corrigido.
6. ⚠️ Benchmark de performance — N/A (sem hot path tocado).
7. ⚠️ Cobertura mínima — N/A (sem código Rust/Python alterado).

**Skip justification:** itens 2/3/6/7 não se aplicam a uma change puramente declarativa (TOML de documentação de versão). O único efeito é fazer `doctor` falhar cedo em drift futuro — coberto pelo item 4.

### 5. Close-gate
- PR aberta (Draft), **não mergeada** (mandato do usuário).
- `git merge-base --is-ancestor c0fc0953e origin/main` → false (não no main).
- Evidência de live re-query: PR #409 `state: open, merged: false`.
