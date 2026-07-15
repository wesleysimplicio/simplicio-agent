#!/usr/bin/env python3
"""test_nest_depthn.py — Testes pytest dedicados ao issue #123.

Critérios de aceite:
- test_depthn_clean_apex: árvore limpa → apex subtree_ok is True
- test_depthn_every_level_caught: falha em depth d nomeada @depth{d}
- test_depthn_is_prime_n: N=7 é primo
- test_depthn_node_count: árvore B=2 depth=7 tem 255 nós
- test_depthn_selftest_pass: --selftest imprime PASS e sai com 0
- test_depthn_parity: parity entre asolaria-patterns e asolaria/asolaria-patterns
"""

import contextlib
import io
import os
import runpy
import sys

# ---- path setup (sem install) -----------------------------------------------
_HERE = os.path.dirname(__file__)
LIB_MAIN = os.path.abspath(os.path.join(_HERE, "..", "skills", "asolaria-patterns", "lib"))
LIB_PARITY = os.path.abspath(
    os.path.join(_HERE, "..", "skills", "asolaria", "asolaria-patterns", "lib")
)
sys.path.insert(0, LIB_PARITY)
sys.path.insert(0, LIB_MAIN)

from nest_depthn import B, N, is_prime, run_tree, hash_tree  # noqa: E402


# ---- testes ------------------------------------------------------------------


def test_depthn_is_prime_n():
    """N=7 deve ser primo (AC explícito do issue)."""
    assert is_prime(N) is True
    assert N == 7


def test_depthn_clean_apex():
    """Árvore limpa: apex gate_ok e subtree_ok são True, sem falhas."""
    tree = run_tree(None)
    assert tree.gate_ok is True
    assert tree.subtree_ok is True
    assert tree.fail_by_depth == {}
    assert tree.fail == []


def test_depthn_node_count():
    """Árvore B=2 depth N=7 deve ter (2^8 − 1) / (2−1) = 255 nós."""
    tree = run_tree(None)
    expected = (B ** (N + 1) - 1) // (B - 1)
    assert len(tuple(tree.iter_nodes())) == expected == 255


def test_depthn_every_level_caught():
    """Falha em cada nível d ∈ 1..N é capturada em @depth{d}, sem false-positives."""
    for d in range(1, N + 1):
        tamper = "R" + ".0" * d
        tree = run_tree(tamper)
        tampered_node = tree.find(tamper)

        assert tree.subtree_ok is False, f"level {d}: apex deveria ser False"
        assert tampered_node is not None, f"level {d}: nó tamperado não encontrado"
        assert tampered_node.gate_ok is False, f"level {d}: gate_ok do nó deveria ser False"

        # fail_by_depth deve ter EXATAMENTE a profundidade d
        assert set(tree.fail_by_depth) == {d}, (
            f"level {d}: fail_by_depth tem chaves erradas: {set(tree.fail_by_depth)}"
        )
        assert tree.fail_by_depth[d] == (f"{tamper}@depth{d}",), (
            f"level {d}: label errado: {tree.fail_by_depth[d]}"
        )


def test_depthn_no_false_positive():
    """Falha em R.0.0.0.0.0.0.0 (depth 7) NÃO deve contaminar nó irmão."""
    tamper = "R" + ".0" * N
    tree = run_tree(tamper)
    sibling = "R" + ".0" * (N - 1) + ".1"
    sib_node = tree.find(sibling)
    assert sib_node is not None
    assert sib_node.gate_ok is True, "irmão do nó tamperado não deve ter gate_ok=False"


def test_depthn_hash_tree_alias():
    """hash_tree() deve ser alias de run_tree() — mesma raiz reported."""
    t1 = run_tree(None)
    t2 = hash_tree(None)
    assert t1.reported == t2.reported
    assert t1.subtree_ok == t2.subtree_ok


def test_depthn_selftest_exits_zero():
    """`python3 nest_depthn.py --selftest` deve imprimir PASS e sair 0."""
    path = os.path.join(LIB_MAIN, "nest_depthn.py")
    out = io.StringIO()
    err = io.StringIO()
    old_argv = sys.argv
    sys.argv = [path, "--selftest"]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                runpy.run_path(path, run_name="__main__")
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
            else:
                code = 0
    finally:
        sys.argv = old_argv
    receipt = out.getvalue()
    assert code == 0, f"selftest saiu com {code}: {err.getvalue()}"
    assert "PASS" in receipt, f"selftest faltou PASS: {receipt}"
    assert "EVERY-LEVEL-CATCHES-CONFABULATION=True" in receipt


def test_depthn_parity_selftest():
    """O módulo em asolaria/ (parity) deve ter o mesmo comportamento."""
    path_parity = os.path.join(LIB_PARITY, "nest_depthn.py")
    out = io.StringIO()
    err = io.StringIO()
    old_argv = sys.argv
    sys.argv = [path_parity, "--selftest"]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                runpy.run_path(path_parity, run_name="__main__")
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
            else:
                code = 0
    finally:
        sys.argv = old_argv
    receipt = out.getvalue()
    assert code == 0, f"parity selftest saiu com {code}: {err.getvalue()}"
    assert "PASS" in receipt
    assert "EVERY-LEVEL-CATCHES-CONFABULATION=True" in receipt
