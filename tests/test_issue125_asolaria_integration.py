"""Testes de integração para issue #125 — Padrões Asolaria no runtime.

Critérios de aceite:
- Todos os testes passam (15/15 do selftest interno)
- Selftests rodam em <1s
- Validação cross-repo ok (facade carrega módulos do skill-tree)
- Zero alterações funcionais nos módulos originais
"""

from __future__ import annotations

import time
from pathlib import Path

from simplicio_agent import asolaria


# ---------------------------------------------------------------------------
# AC1: Padrão N-Nest — árvore de verificação hierárquica
# ---------------------------------------------------------------------------

def test_n_nest_apex_clean():
    """Árvore sem tamper: apex gate_ok e subtree_ok devem ser True."""
    apex = asolaria.run_n_nest()
    assert apex.gate_ok is True
    assert apex.subtree_ok is True
    assert apex.fail == []
    assert apex.fail_by_depth == {}


def test_n_nest_tamper_caught_at_leaf():
    """Confabulação em folha (depth=7) é detectada pelo gate local."""
    tamper = "R.0.0.0.0.0.0.0"
    apex = asolaria.run_n_nest(tamper)
    assert apex.subtree_ok is False
    node = apex.find(tamper)
    assert node is not None
    assert node.gate_ok is False


def test_n_nest_tamper_caught_at_depth1():
    """Confabulação no nível 1 propaga até o apex."""
    tamper = "R.0"
    apex = asolaria.run_n_nest(tamper)
    assert apex.subtree_ok is False
    assert 1 in apex.fail_by_depth


def test_n_nest_every_depth_caught():
    """Gate corretivo detecta confabulação em TODOS os níveis 1..N."""
    for d in range(1, 8):  # N=7
        tamper = "R" + ".0" * d
        apex = asolaria.run_n_nest(tamper)
        assert apex.subtree_ok is False, f"nível {d} não foi detectado"
        assert d in apex.fail_by_depth, f"fail_by_depth não registrou nível {d}"


def test_n_nest_no_false_positive():
    """Tamper em um nó não contamina outro nó não afetado."""
    tamper = "R.1.0.0.0.0.0.0"
    apex = asolaria.run_n_nest(tamper)
    other = apex.find("R.0")
    assert other is not None
    assert other.gate_ok is True


def test_n_nest_determinism():
    """run_n_nest() é determinística: duas chamadas produzem o mesmo apex."""
    a1 = asolaria.run_n_nest()
    a2 = asolaria.run_n_nest()
    assert a1.reported == a2.reported
    assert a1.true_hash == a2.true_hash


# ---------------------------------------------------------------------------
# AC2: Padrão PRISM-COMB — bijection invariante 0-loss
# ---------------------------------------------------------------------------

def test_prism_forward_deterministic():
    """forward(addr) retorna o mesmo int em chamadas repetidas."""
    addr = "R.2.1.0"
    assert asolaria.prism_forward(addr) == asolaria.prism_forward(addr)


def test_prism_round_trip():
    """f⁻¹(f(v)) == v para vários endereços (bijection fecha)."""
    for a in range(4):
        for b in range(4):
            addr = f"R.{a}.{b}"
            v = asolaria.prism_forward(addr)
            s = asolaria.prism_seal(v)
            ok, recomputed = asolaria.prism_inverse(addr, s)
            assert ok is True
            assert recomputed == v


def test_prism_confabulation_no_inverse():
    """Seal confabulado não fecha a bijection inversa."""
    addr = "R.0.0.0"
    ok, _ = asolaria.prism_inverse(addr, "confabulated_deadbeef")
    assert ok is False


def test_prism_crt_capacity():
    """Capacidade CRT = produto dos módulos (3×5×17×257)."""
    cap = asolaria.prism_crt_capacity()
    assert cap == 3 * 5 * 17 * 257


def test_prism_crt_lossless_within_capacity():
    """CRT recombina sem perda dentro da capacidade declarada."""
    cap = asolaria.prism_crt_capacity()
    for x in (0, 1, cap // 2, cap - 1):
        residues = asolaria.prism_crt_decompose(x)
        status, val = asolaria.prism_crt_recombine(residues, domain_size=cap)
        assert status == "ok", f"x={x} status={status}"
        assert val == x, f"x={x} recombined={val}"


def test_prism_crt_held_outside_capacity():
    """Domínio > capacidade retorna 'held' (recusa resposta imprecisa)."""
    cap = asolaria.prism_crt_capacity()
    residues = asolaria.prism_crt_decompose(cap - 1)
    status, val = asolaria.prism_crt_recombine(residues, domain_size=cap + 1)
    assert status == "held"
    assert val is None


# ---------------------------------------------------------------------------
# AC3: Selftests integrados rodam em <1s
# ---------------------------------------------------------------------------

def test_selftest_timing():
    """Selftest completo (nest + prism + geometry) em menos de 1 segundo."""
    t0 = time.perf_counter()
    result = asolaria.selftest()
    elapsed = time.perf_counter() - t0
    assert result == 0
    assert elapsed < 1.0, f"selftest levou {elapsed:.3f}s (limite: 1s)"


# ---------------------------------------------------------------------------
# AC4: Validação cross-repo — facade carrega módulos do skill-tree sem cópias
# ---------------------------------------------------------------------------

def test_facade_loads_from_skill_tree():
    """Os módulos são carregados do skills/asolaria-patterns/lib, sem cópia."""
    repo_root = Path(__file__).resolve().parents[1]
    skill_lib = repo_root / "skills" / "asolaria-patterns" / "lib"

    assert (skill_lib / "nest_depthn.py").is_file(), "nest_depthn.py ausente"
    assert (skill_lib / "prism_comb.py").is_file(), "prism_comb.py ausente"

    # Verifica que o facade não duplicou os arquivos no pacote simplicio_agent
    agent_pkg = repo_root / "simplicio_agent"
    assert not (agent_pkg / "nest_depthn.py").exists(), "nest_depthn.py não deve ser copiado"
    assert not (agent_pkg / "prism_comb.py").exists(), "prism_comb.py não deve ser copiado"


def test_facade_module_identity():
    """O módulo carregado é o mesmo em chamadas consecutivas (cache ativo)."""
    m1 = asolaria._load_pattern("nest_depthn")
    m2 = asolaria._load_pattern("nest_depthn")
    assert m1 is m2, "facade deve retornar o mesmo objeto de módulo (cache)"


def test_asolaria_module_exported_api():
    """Todas as funções do __all__ da facade são acessíveis."""
    expected = {
        "addressing_geometry", "citizen_identity", "encode_addr", "fnv1a64",
        "prism_crt_capacity", "prism_crt_decompose", "prism_crt_recombine",
        "prism_forward", "prism_inverse", "prism_seal", "realmathpos",
        "run_n_nest", "selftest", "sha16", "verify_citizen",
    }
    for name in expected:
        assert hasattr(asolaria, name), f"asolaria.{name} não encontrado"
