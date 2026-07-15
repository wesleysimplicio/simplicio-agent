"""
tests/test_unified_harness.py — Testes para agent.testing.unified_harness (#47).
"""

from __future__ import annotations

import pytest

from agent.testing.unified_harness import TestCase, UnifiedTestHarness


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _passing_fn() -> None:
    assert 1 + 1 == 2


def _failing_fn() -> None:
    raise AssertionError("falha intencional")


def _tagged_fn() -> None:
    assert "simplicio" in "simplicio-agent"


# ---------------------------------------------------------------------------
# 1. TestCase — validações básicas
# ---------------------------------------------------------------------------


class TestTestCase:
    def test_creation_ok(self):
        """TestCase é criado com campos corretos."""
        tc = TestCase(id="t-01", description="Desc", fn=_passing_fn, tags=["unit"])
        assert tc.id == "t-01"
        assert tc.description == "Desc"
        assert tc.fn is _passing_fn
        assert tc.tags == ["unit"]

    def test_default_tags_empty(self):
        """Tags padrão são lista vazia."""
        tc = TestCase(id="t-02", description="Sem tags", fn=_passing_fn)
        assert tc.tags == []

    def test_empty_id_raises(self):
        """Id vazio deve lançar ValueError."""
        with pytest.raises(ValueError, match="id"):
            TestCase(id="", description="Bad", fn=_passing_fn)

    def test_non_callable_fn_raises(self):
        """fn não callable deve lançar TypeError."""
        with pytest.raises(TypeError, match="callable"):
            TestCase(id="t-03", description="Bad fn", fn="not_a_function")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. UnifiedTestHarness — registro
# ---------------------------------------------------------------------------


class TestHarnessRegister:
    def test_register_and_count(self):
        """Harness deve registrar caso e mantê-lo interno."""
        h = UnifiedTestHarness()
        h.register(TestCase(id="r-01", description="R1", fn=_passing_fn))
        assert len(h._cases) == 1

    def test_duplicate_id_raises(self):
        """Registrar id duplicado lança ValueError."""
        h = UnifiedTestHarness()
        h.register(TestCase(id="dup", description="D1", fn=_passing_fn))
        with pytest.raises(ValueError, match="dup"):
            h.register(TestCase(id="dup", description="D2", fn=_passing_fn))

    def test_register_wrong_type_raises(self):
        """Registrar objeto que não é TestCase lança TypeError."""
        h = UnifiedTestHarness()
        with pytest.raises(TypeError):
            h.register({"id": "x"})  # type: ignore[arg-type]

    def test_register_fn_decorator(self):
        """Decorator register_fn registra o caso corretamente."""
        h = UnifiedTestHarness()

        @h.register_fn(id="dec-01", description="Via decorator", tags=["unit"])
        def my_test() -> None:
            assert True

        assert "dec-01" in h._cases
        assert h._cases["dec-01"].tags == ["unit"]


# ---------------------------------------------------------------------------
# 3. UnifiedTestHarness — run_all
# ---------------------------------------------------------------------------


class TestHarnessRunAll:
    def test_run_all_all_pass(self):
        """run_all retorna True para casos que passam."""
        h = UnifiedTestHarness()
        h.register(TestCase(id="a-01", description="A1", fn=_passing_fn))
        h.register(TestCase(id="a-02", description="A2", fn=_tagged_fn))
        results = h.run_all()
        assert results == {"a-01": True, "a-02": True}

    def test_run_all_with_failure(self):
        """run_all retorna False para casos que falham."""
        h = UnifiedTestHarness()
        h.register(TestCase(id="b-01", description="B1", fn=_passing_fn))
        h.register(TestCase(id="b-02", description="B2 (falha)", fn=_failing_fn))
        results = h.run_all()
        assert results["b-01"] is True
        assert results["b-02"] is False

    def test_run_all_empty_harness(self):
        """run_all em harness vazio retorna dict vazio."""
        h = UnifiedTestHarness()
        assert h.run_all() == {}


# ---------------------------------------------------------------------------
# 4. UnifiedTestHarness — run_tagged
# ---------------------------------------------------------------------------


class TestHarnessRunTagged:
    def test_run_tagged_returns_only_tagged(self):
        """run_tagged retorna apenas os casos com a tag solicitada."""
        h = UnifiedTestHarness()
        h.register(TestCase(id="tag-01", description="T1", fn=_passing_fn, tags=["unit"]))
        h.register(TestCase(id="tag-02", description="T2", fn=_tagged_fn, tags=["integration"]))
        h.register(TestCase(id="tag-03", description="T3", fn=_passing_fn, tags=["unit"]))

        results = h.run_tagged("unit")
        assert set(results.keys()) == {"tag-01", "tag-03"}
        assert all(results.values())

    def test_run_tagged_no_match_returns_empty(self):
        """run_tagged sem correspondência retorna dict vazio."""
        h = UnifiedTestHarness()
        h.register(TestCase(id="nt-01", description="NT1", fn=_passing_fn, tags=["unit"]))
        assert h.run_tagged("e2e") == {}

    def test_run_tagged_failing_case(self):
        """run_tagged captura falhas em casos taggeados."""
        h = UnifiedTestHarness()
        h.register(TestCase(id="tf-01", description="TF1 falha", fn=_failing_fn, tags=["ci"]))
        results = h.run_tagged("ci")
        assert results["tf-01"] is False


# ---------------------------------------------------------------------------
# 5. UnifiedTestHarness — report
# ---------------------------------------------------------------------------


class TestHarnessReport:
    def test_report_contains_pass_and_fail(self):
        """report() inclui [PASS] e [FAIL] para casos respectivos."""
        h = UnifiedTestHarness()
        h.register(TestCase(id="rp-01", description="Passa", fn=_passing_fn))
        h.register(TestCase(id="rp-02", description="Falha", fn=_failing_fn))
        rpt = h.report()
        assert "[PASS] rp-01" in rpt
        assert "[FAIL] rp-02" in rpt

    def test_report_summary_counts(self):
        """report() exibe contagens corretas no rodapé."""
        h = UnifiedTestHarness()
        h.register(TestCase(id="rc-01", description="P1", fn=_passing_fn))
        h.register(TestCase(id="rc-02", description="P2", fn=_passing_fn))
        h.register(TestCase(id="rc-03", description="F1", fn=_failing_fn))
        rpt = h.report()
        assert "Total: 3" in rpt
        assert "Passed: 2" in rpt
        assert "Failed: 1" in rpt

    def test_report_header(self):
        """report() começa com cabeçalho 'Unified Test Report'."""
        h = UnifiedTestHarness()
        rpt = h.report()
        assert rpt.startswith("Unified Test Report")


# ---------------------------------------------------------------------------
# 6. pytest_items
# ---------------------------------------------------------------------------


class TestPytestItems:
    def test_pytest_items_returns_list(self):
        """pytest_items() retorna lista de dicts com chaves esperadas."""
        h = UnifiedTestHarness()
        h.register(TestCase(id="pi-01", description="PI1", fn=_passing_fn, tags=["unit"]))
        items = h.pytest_items()
        assert len(items) == 1
        item = items[0]
        assert item["id"] == "pi-01"
        assert item["description"] == "PI1"
        assert item["tags"] == ["unit"]
        assert item["fn"] is _passing_fn
