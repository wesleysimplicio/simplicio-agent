"""Shannon — Pipeline Adversarial 4 Fases.

Implementação do pipeline adversarial inspirado no modelo Shannon:

  Fase 1 — Recon:         mapeamento completo do alvo
  Fase 2 — VulnAnalysis:  revisão adversarial multi-rubrica
  Fase 3 — Execution:     execução controlada com gate L0-L6
  Fase 4 — Reporting:     entrega com evidência ("No Exploit, No Report")

Referências: simplicio-loop #94 (shannon + Gulp), Issue Mestra #25.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


# ---------------------------------------------------------------------------
# Verdict Router L0–L6
# ---------------------------------------------------------------------------

class VerdictLevel(IntEnum):
    """Nível de risco/exploitabilidade L0–L6 do Verdict Router.

    L0 = sem risco; L6 = crítico / exploitable com evidência confirmada.
    """

    L0 = 0  # Nenhum risco identificado
    L1 = 1  # Informacional — sem exploitabilidade
    L2 = 2  # Baixo — exploitabilidade teórica
    L3 = 3  # Médio — exploitabilidade limitada
    L4 = 4  # Alto — exploitabilidade provável
    L5 = 5  # Crítico — exploitabilidade confirmada
    L6 = 6  # Crítico + prova de exploração ativa


# Limiar mínimo para o gate de execução liberar a Fase 3
_EXECUTION_GATE_THRESHOLD = VerdictLevel.L2


# ---------------------------------------------------------------------------
# Estruturas de dados
# ---------------------------------------------------------------------------

@dataclass
class ReconReport:
    """Saída da Fase 1 — Recon."""

    target: str
    surface_map: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0


@dataclass
class VulnReport:
    """Saída da Fase 2 — VulnAnalysis."""

    findings: list[dict[str, Any]] = field(default_factory=list)
    verdict: VerdictLevel = VerdictLevel.L0
    rubrics: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0


@dataclass
class ExecutionReport:
    """Saída da Fase 3 — Execution."""

    ran: bool = False
    gate_passed: bool = False
    gate_reason: str = ""
    artifacts: list[Any] = field(default_factory=list)
    elapsed_ms: float = 0.0


@dataclass
class FinalReport:
    """Saída da Fase 4 — Reporting."""

    title: str = ""
    summary: str = ""
    verdict: VerdictLevel = VerdictLevel.L0
    evidence: list[dict[str, Any]] = field(default_factory=list)
    has_exploit: bool = False
    elapsed_ms: float = 0.0


@dataclass
class PipelineResult:
    """Resultado consolidado das 4 fases."""

    target: str
    recon: ReconReport | None = None
    vuln: VulnReport | None = None
    execution: ExecutionReport | None = None
    report: FinalReport | None = None
    total_elapsed_ms: float = 0.0
    success: bool = False
    error: str = ""


# ---------------------------------------------------------------------------
# Fase 1 — Recon
# ---------------------------------------------------------------------------

class Phase1Recon:
    """Fase 1: mapeamento completo do alvo.

    Responsável por enumerar a superfície de ataque: endpoints, dependências,
    permissões, metadados de ambiente e qualquer artefato relevante para as
    fases seguintes.
    """

    def __init__(self, depth: int = 1) -> None:
        """
        Args:
            depth: profundidade do mapeamento (1 = superficial, 3 = profundo).
        """
        self.depth = max(1, min(depth, 3))

    def run(self, target: str, context: dict[str, Any] | None = None) -> ReconReport:
        """Executa o reconhecimento sobre *target*.

        Args:
            target: identificador do alvo (nome, URL, path, etc.).
            context: dados de contexto opcionais fornecidos pelo orquestrador.

        Returns:
            ReconReport com superfície mapeada e metadados coletados.
        """
        t0 = time.monotonic()
        ctx = context or {}

        surface_map: dict[str, Any] = {
            "target": target,
            "depth": self.depth,
            "endpoints": ctx.get("endpoints", []),
            "dependencies": ctx.get("dependencies", []),
            "permissions": ctx.get("permissions", []),
            "entry_points": ctx.get("entry_points", [target]),
        }

        if self.depth >= 2:
            surface_map["transitive_deps"] = ctx.get("transitive_deps", [])
            surface_map["config_files"] = ctx.get("config_files", [])

        if self.depth >= 3:
            surface_map["network_topology"] = ctx.get("network_topology", {})
            surface_map["auth_mechanisms"] = ctx.get("auth_mechanisms", [])

        metadata: dict[str, Any] = {
            "recon_depth": self.depth,
            "timestamp": time.time(),
            "context_keys_received": list(ctx.keys()),
        }

        elapsed = (time.monotonic() - t0) * 1000
        return ReconReport(
            target=target,
            surface_map=surface_map,
            metadata=metadata,
            elapsed_ms=round(elapsed, 3),
        )


# ---------------------------------------------------------------------------
# Fase 2 — VulnAnalysis
# ---------------------------------------------------------------------------

# Rubricas de avaliação adversarial
_DEFAULT_RUBRICS: list[str] = [
    "injection",          # injeção de código/comando
    "privilege_escalation",
    "data_exposure",
    "auth_bypass",
    "supply_chain",
    "insecure_defaults",
]


class Phase2VulnAnalysis:
    """Fase 2: revisão adversarial multi-rubrica.

    Avalia a superfície mapeada na Fase 1 contra um conjunto de rubricas de
    segurança, produzindo um veredito L0–L6 e lista de findings.
    """

    def __init__(self, rubrics: list[str] | None = None) -> None:
        self.rubrics = rubrics or _DEFAULT_RUBRICS

    def run(
        self,
        recon: ReconReport,
        extra_findings: list[dict[str, Any]] | None = None,
    ) -> VulnReport:
        """Executa análise de vulnerabilidades sobre o ReconReport.

        Args:
            recon: saída da Fase 1.
            extra_findings: findings injetados externamente (para testes /
                integrações com scanners externos).

        Returns:
            VulnReport com verdict L0–L6 e rubricas avaliadas.
        """
        t0 = time.monotonic()
        findings: list[dict[str, Any]] = list(extra_findings or [])

        rubric_scores: dict[str, int] = {}
        for rubric in self.rubrics:
            score = self._score_rubric(rubric, recon)
            rubric_scores[rubric] = score
            if score > 0:
                findings.append(
                    {
                        "rubric": rubric,
                        "score": score,
                        "target": recon.target,
                        "detail": f"Rubric '{rubric}' scored {score} on surface map.",
                    }
                )

        max_score = max(rubric_scores.values(), default=0)
        # Mapeia score [0–6] para VerdictLevel
        verdict = VerdictLevel(min(max_score, 6))

        elapsed = (time.monotonic() - t0) * 1000
        return VulnReport(
            findings=findings,
            verdict=verdict,
            rubrics=rubric_scores,
            elapsed_ms=round(elapsed, 3),
        )

    # ------------------------------------------------------------------
    # helpers internos
    # ------------------------------------------------------------------

    def _score_rubric(self, rubric: str, recon: ReconReport) -> int:
        """Retorna score 0–6 para uma rubrica dada a superfície mapeada.

        Implementação heurística: em produção, substituir por LLM call ou
        scanner especializado.
        """
        surface = recon.surface_map
        score = 0

        if rubric == "injection":
            if surface.get("endpoints"):
                score = 2
            if surface.get("entry_points"):
                score = min(score + 1, 6)

        elif rubric == "privilege_escalation":
            perms = surface.get("permissions", [])
            if any("admin" in str(p).lower() or "root" in str(p).lower() for p in perms):
                score = 4

        elif rubric == "data_exposure":
            config_files = surface.get("config_files", [])
            if any(".env" in str(f) or "secret" in str(f).lower() for f in config_files):
                score = 3

        elif rubric == "auth_bypass":
            auth = surface.get("auth_mechanisms", [])
            if "none" in [str(a).lower() for a in auth]:
                score = 5

        elif rubric == "supply_chain":
            deps = surface.get("dependencies", [])
            if len(deps) > 10:
                score = 2

        elif rubric == "insecure_defaults":
            if surface.get("depth", 1) >= 2 and not surface.get("auth_mechanisms"):
                score = 1

        return score


# ---------------------------------------------------------------------------
# Fase 3 — Execution (com gate)
# ---------------------------------------------------------------------------

class Phase3Execution:
    """Fase 3: execução controlada com gate L0–L6.

    O gate só libera a execução quando o veredito da Fase 2 atingir ou
    ultrapassar o limiar configurado (_EXECUTION_GATE_THRESHOLD).

    Sem gate aprovado → nenhuma execução ocorre e o pipeline continua para
    o Reporting sem artefatos.
    """

    def __init__(
        self,
        gate_threshold: VerdictLevel = _EXECUTION_GATE_THRESHOLD,
        executor: Any | None = None,
    ) -> None:
        """
        Args:
            gate_threshold: nível mínimo de veredito para liberar execução.
            executor: callable(recon, vuln) → list[Any] para substituição em testes.
        """
        self.gate_threshold = gate_threshold
        self._executor = executor

    def run(self, recon: ReconReport, vuln: VulnReport) -> ExecutionReport:
        """Avalia gate e, se aprovado, executa ações sobre o alvo.

        Args:
            recon: saída da Fase 1.
            vuln:  saída da Fase 2.

        Returns:
            ExecutionReport indicando se a execução ocorreu e quais artefatos
            foram produzidos.
        """
        t0 = time.monotonic()

        if vuln.verdict < self.gate_threshold:
            elapsed = (time.monotonic() - t0) * 1000
            return ExecutionReport(
                ran=False,
                gate_passed=False,
                gate_reason=(
                    f"Verdict {vuln.verdict.name} ({vuln.verdict}) is below "
                    f"gate threshold {self.gate_threshold.name} ({self.gate_threshold}). "
                    "Execution skipped."
                ),
                elapsed_ms=round(elapsed, 3),
            )

        # Gate aprovado — executa
        artifacts: list[Any] = []
        if self._executor is not None:
            artifacts = self._executor(recon, vuln)
        else:
            # Execução padrão: registra findings como artefato de evidência
            artifacts = [
                {"type": "evidence_snapshot", "finding": f, "target": recon.target}
                for f in vuln.findings
            ]

        elapsed = (time.monotonic() - t0) * 1000
        return ExecutionReport(
            ran=True,
            gate_passed=True,
            gate_reason=f"Gate passed at verdict {vuln.verdict.name}.",
            artifacts=artifacts,
            elapsed_ms=round(elapsed, 3),
        )


# ---------------------------------------------------------------------------
# Fase 4 — Reporting
# ---------------------------------------------------------------------------

class Phase4Reporting:
    """Fase 4: entrega com evidência ("No Exploit, No Report").

    Consolida todos os artefatos das fases anteriores em um relatório final.
    Relatórios com verdict L0/L1 são marcados como sem exploit e omitidos
    do canal principal (apenas auditoria interna).
    """

    def run(
        self,
        recon: ReconReport,
        vuln: VulnReport,
        execution: ExecutionReport,
    ) -> FinalReport:
        """Gera relatório final consolidado.

        Args:
            recon:     saída da Fase 1.
            vuln:      saída da Fase 2.
            execution: saída da Fase 3.

        Returns:
            FinalReport com título, resumo, veredito e evidências coletadas.
        """
        t0 = time.monotonic()
        has_exploit = execution.ran and len(execution.artifacts) > 0

        evidence: list[dict[str, Any]] = []

        # Evidência de reconhecimento
        evidence.append(
            {
                "phase": "recon",
                "target": recon.target,
                "surface_keys": list(recon.surface_map.keys()),
                "elapsed_ms": recon.elapsed_ms,
            }
        )

        # Evidência de análise
        evidence.append(
            {
                "phase": "vuln_analysis",
                "verdict": vuln.verdict.name,
                "finding_count": len(vuln.findings),
                "rubrics": vuln.rubrics,
                "elapsed_ms": vuln.elapsed_ms,
            }
        )

        # Evidência de execução
        evidence.append(
            {
                "phase": "execution",
                "ran": execution.ran,
                "gate_passed": execution.gate_passed,
                "artifact_count": len(execution.artifacts),
                "elapsed_ms": execution.elapsed_ms,
            }
        )

        title = (
            f"[{vuln.verdict.name}] Shannon Adversarial Report — {recon.target}"
        )

        if has_exploit:
            summary = (
                f"Target '{recon.target}' presented {len(vuln.findings)} finding(s) "
                f"with verdict {vuln.verdict.name}. "
                f"{len(execution.artifacts)} exploit artifact(s) produced."
            )
        elif vuln.findings:
            summary = (
                f"Target '{recon.target}' presented {len(vuln.findings)} finding(s) "
                f"with verdict {vuln.verdict.name}. No exploit artifacts produced "
                f"(gate: {execution.gate_reason})."
            )
        else:
            summary = (
                f"Target '{recon.target}' — no significant findings. "
                f"Verdict: {vuln.verdict.name}."
            )

        elapsed = (time.monotonic() - t0) * 1000
        return FinalReport(
            title=title,
            summary=summary,
            verdict=vuln.verdict,
            evidence=evidence,
            has_exploit=has_exploit,
            elapsed_ms=round(elapsed, 3),
        )


# ---------------------------------------------------------------------------
# Orquestrador — AdversarialPipeline
# ---------------------------------------------------------------------------

class AdversarialPipeline:
    """Orquestrador do pipeline adversarial Shannon de 4 fases.

    Exemplo de uso::

        pipeline = AdversarialPipeline()
        result = pipeline.run("meu-servico", context={"endpoints": ["/api/v1"]})
        print(result.report.title)
    """

    def __init__(
        self,
        recon: Phase1Recon | None = None,
        vuln: Phase2VulnAnalysis | None = None,
        execution: Phase3Execution | None = None,
        reporting: Phase4Reporting | None = None,
    ) -> None:
        self.phase1 = recon or Phase1Recon()
        self.phase2 = vuln or Phase2VulnAnalysis()
        self.phase3 = execution or Phase3Execution()
        self.phase4 = reporting or Phase4Reporting()

    def run(
        self,
        target: str,
        context: dict[str, Any] | None = None,
        extra_findings: list[dict[str, Any]] | None = None,
    ) -> PipelineResult:
        """Executa as 4 fases em sequência sobre *target*.

        Args:
            target:        identificador do alvo.
            context:       contexto passado para a Fase 1.
            extra_findings: findings externos para a Fase 2.

        Returns:
            PipelineResult com resultados consolidados de todas as fases.
        """
        t0 = time.monotonic()
        result = PipelineResult(target=target)

        try:
            # Fase 1 — Recon
            recon_report = self.phase1.run(target, context)
            result.recon = recon_report

            # Fase 2 — VulnAnalysis
            vuln_report = self.phase2.run(recon_report, extra_findings)
            result.vuln = vuln_report

            # Fase 3 — Execution (com gate)
            exec_report = self.phase3.run(recon_report, vuln_report)
            result.execution = exec_report

            # Fase 4 — Reporting
            final_report = self.phase4.run(recon_report, vuln_report, exec_report)
            result.report = final_report

            result.success = True

        except Exception as exc:  # noqa: BLE001
            result.error = str(exc)
            result.success = False

        result.total_elapsed_ms = round((time.monotonic() - t0) * 1000, 3)
        return result
