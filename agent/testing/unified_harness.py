"""
unified_harness.py — Unified Test Harness para Simplicio Agent (#47).

Fornece TestCase (dataclass) e UnifiedTestHarness para registrar, executar e
reportar testes de forma unificada, com suporte a tags e integração com pytest.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class TestCase:
    """Representa um caso de teste registrável no harness unificado.

    Atributos:
        id:          Identificador único do caso de teste.
        description: Descrição legível do que o teste verifica.
        fn:          Callable sem argumentos que lança exceção em caso de falha.
        tags:        Lista de tags para filtragem (ex.: ["unit", "integration"]).
    """

    id: str
    description: str
    fn: Callable[[], None]
    tags: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("TestCase.id não pode ser vazio")
        if not callable(self.fn):
            raise TypeError("TestCase.fn deve ser callable")


class UnifiedTestHarness:
    """Harness unificado de testes para o Simplicio Agent.

    Permite registrar TestCases, executá-los por conjunto completo ou por tag,
    e gerar relatório em texto.

    Uso básico::

        harness = UnifiedTestHarness()

        @harness.register_fn(id="ex-01", description="Exemplo", tags=["unit"])
        def meu_teste():
            assert 1 + 1 == 2

        results = harness.run_all()
        print(harness.report())

    Integração com pytest:
        Crie um fixture que exponha o harness e use ``harness.run_all()`` dentro
        de um teste pytest; cada entrada do dict pode ser asserted individualmente
        via ``run_tagged``. Ver ``tests/test_unified_harness.py`` para exemplos.
    """

    def __init__(self) -> None:
        self._cases: Dict[str, TestCase] = {}

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------

    def register(self, case: TestCase) -> None:
        """Registra um TestCase no harness.

        Lança ValueError se o id já estiver registrado.
        """
        if not isinstance(case, TestCase):
            raise TypeError(f"Esperado TestCase, recebido {type(case).__name__}")
        if case.id in self._cases:
            raise ValueError(f"TestCase com id '{case.id}' já registrado")
        self._cases[case.id] = case

    def register_fn(
        self,
        id: str,
        description: str,
        tags: Optional[List[str]] = None,
    ) -> Callable[[Callable[[], None]], Callable[[], None]]:
        """Decorador conveniente para registrar uma função como TestCase."""

        def decorator(fn: Callable[[], None]) -> Callable[[], None]:
            self.register(
                TestCase(
                    id=id,
                    description=description,
                    fn=fn,
                    tags=tags or [],
                )
            )
            return fn

        return decorator

    # ------------------------------------------------------------------
    # Execução
    # ------------------------------------------------------------------

    def _run_case(self, case: TestCase) -> bool:
        """Executa um único TestCase. Retorna True se passou, False se falhou."""
        try:
            case.fn()
            return True
        except Exception:
            return False

    def run_all(self) -> Dict[str, bool]:
        """Executa todos os TestCases registrados.

        Retorna:
            dict mapeando id → True (passou) / False (falhou).
        """
        return {cid: self._run_case(case) for cid, case in self._cases.items()}

    def run_tagged(self, tag: str) -> Dict[str, bool]:
        """Executa apenas os TestCases que possuem a tag informada.

        Retorna:
            dict mapeando id → True (passou) / False (falhou).
            Vazio se nenhum caso tiver a tag.
        """
        return {
            cid: self._run_case(case)
            for cid, case in self._cases.items()
            if tag in case.tags
        }

    # ------------------------------------------------------------------
    # Relatório
    # ------------------------------------------------------------------

    def report(self) -> str:
        """Executa todos os testes e retorna um relatório em texto.

        Formato::

            Unified Test Report
            ===================
            [PASS] id-01  — Descrição do teste
            [FAIL] id-02  — Outro teste
            ---
            Total: 2 | Passed: 1 | Failed: 1
        """
        results = self.run_all()
        lines: List[str] = ["Unified Test Report", "=" * 19]

        for cid, passed in results.items():
            case = self._cases[cid]
            status = "PASS" if passed else "FAIL"
            lines.append(f"[{status}] {cid}  — {case.description}")

        total = len(results)
        passed_count = sum(1 for v in results.values() if v)
        failed_count = total - passed_count
        lines.append("-" * 19)
        lines.append(
            f"Total: {total} | Passed: {passed_count} | Failed: {failed_count}"
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Integração pytest
    # ------------------------------------------------------------------

    def pytest_items(self) -> List[dict]:
        """Retorna lista de dicts descritivos dos casos — útil para parametrize.

        Cada dict contém: id, description, tags, fn.
        """
        return [
            {
                "id": case.id,
                "description": case.description,
                "tags": case.tags,
                "fn": case.fn,
            }
            for case in self._cases.values()
        ]
