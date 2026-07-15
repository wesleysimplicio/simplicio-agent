# Padrões Asolaria no Simplicio Agent — ARCHITECTURE.md

## Contexto (issue #125)

Este documento descreve a integração dos módulos Asolaria N-Nest e PRISM-COMB
no Simplicio Agent via facade determinístico em `simplicio_agent/asolaria.py`.

---

## Módulos portados

| Módulo | Localização | Responsabilidade |
|--------|-------------|-----------------|
| `nest_depthn.py` | `skills/asolaria-patterns/lib/` | Árvore de verificação hierárquica N-Nest Prime (B=2, N=7 primo) |
| `prism_comb.py` | `skills/asolaria-patterns/lib/` | Lei PRISM-COMB 0-loss: bijection invariante + CRT capacity gate |

---

## Facade: `simplicio_agent.asolaria`

O módulo `simplicio_agent/asolaria.py` expõe a API pública sem duplicar os
arquivos-fonte. O carregamento é feito via `importlib.util.spec_from_file_location`
e os módulos são mantidos em cache (`_MODULES`) para evitar re-execução.

```python
from simplicio_agent import asolaria

# N-Nest: árvore sem tamper
apex = asolaria.run_n_nest()
assert apex.subtree_ok is True

# N-Nest: confabulação detectada em qualquer nível
tampered = asolaria.run_n_nest("R.0.0.0")
assert tampered.subtree_ok is False

# PRISM-COMB: bijection round-trip
v = asolaria.prism_forward("R.0.0.0")
seal = asolaria.prism_seal(v)
ok, recomputed = asolaria.prism_inverse("R.0.0.0", seal)
assert ok is True and recomputed == v

# Selftest completo
assert asolaria.selftest() == 0  # < 1s
```

---

## Contratos verificados

### N-Nest Prime (nest_depthn.py)

- **Branching factor** B = 2, **Profundidade** N = 7 (primo)
- `leaf.true = sha16("work|" + addr)`
- `internal.true = sha16(addr | ",".join(children.reported))`
- `node.gate_ok = (reported == true)` — gate corretivo local
- `subtree_ok = gate_ok AND all(child.subtree_ok)`
- Confabulação em **qualquer** nível 1..N → detectada naquele nível exato

### PRISM-COMB 0-loss (prism_comb.py)

- **Bijection**: `f⁻¹(f(v)) == v` para todo `v` no domínio
- **Entropy invariante**: `H(f(X)) == H(X)` (relabeling 1:1 não altera frequências)
- **CRT capacity gate**: `crt_recombine()` retorna `("held", None)` quando
  `domain_size > M` — recusa resposta imprecisa em vez de silenciosamente
  retornar `x mod M`
- **Confabulação sem inverso**: seal fabricado não fecha o round-trip

---

## Limites desta integração

Este é um slice de integração de checkout. A facade carrega os módulos Python
diretamente do skill-tree; ela **não** prova que o `simplicio-runtime` (Rust)
consome estes módulos ou compartilha seus vetores. A integração cross-repo no
nível Rust é trabalho futuro (ver `docs/ASOLARIA_ABSORPTION_PLAN.md`).

---

## Benchmarks

Executados na máquina de desenvolvimento (Apple M-series):

| Selftest | Tempo medido |
|----------|-------------|
| `asolaria.selftest()` (nest + prism + geometry) | ~22ms |
| Limite declarado no AC | < 1000ms |

---

## Testes

- `tests/test_issue125_asolaria_integration.py` — 16 testes de integração (ACs do issue #125)
- `tests/test_asolaria_public.py` — 8 testes da surface pública da facade
- `skills/asolaria-patterns/tests/test_patterns.py` — 16 testes unitários dos módulos originais
