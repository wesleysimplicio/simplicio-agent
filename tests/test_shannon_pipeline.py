"""Tests for Shannon Adversarial Pipeline (4 fases) — issue #35."""

from __future__ import annotations

import pytest

from agent.shannon.pipeline import (
    AdversarialPipeline,
    Phase1Recon,
    Phase2VulnAnalysis,
    Phase3Execution,
    Phase4Reporting,
    VerdictLevel,
)


# ---------------------------------------------------------------------------
# Fase 1 — Recon
# ---------------------------------------------------------------------------

class TestPhase1Recon:
    def test_basic_recon_returns_report(self):
        phase = Phase1Recon()
        report = phase.run("test-target")
        assert report.target == "test-target"
        assert "target" in report.surface_map
        assert report.elapsed_ms >= 0

    def test_recon_depth1_no_transitive_deps(self):
        phase = Phase1Recon(depth=1)
        report = phase.run("svc", context={"dependencies": ["dep1"]})
        assert "transitive_deps" not in report.surface_map

    def test_recon_depth2_includes_transitive_deps(self):
        phase = Phase1Recon(depth=2)
        report = phase.run("svc", context={"transitive_deps": ["t1", "t2"]})
        assert "transitive_deps" in report.surface_map
        assert report.surface_map["transitive_deps"] == ["t1", "t2"]

    def test_recon_depth3_includes_network_topology(self):
        phase = Phase1Recon(depth=3)
        report = phase.run("svc", context={"network_topology": {"nodes": 5}})
        assert "network_topology" in report.surface_map
        assert report.surface_map["network_topology"]["nodes"] == 5

    def test_recon_metadata_captures_context_keys(self):
        phase = Phase1Recon()
        report = phase.run("svc", context={"endpoints": ["/api"], "permissions": []})
        assert "endpoints" in report.metadata["context_keys_received"]

    def test_recon_depth_clamped(self):
        phase = Phase1Recon(depth=10)
        assert phase.depth == 3


# ---------------------------------------------------------------------------
# Fase 2 — VulnAnalysis
# ---------------------------------------------------------------------------

class TestPhase2VulnAnalysis:
    def test_no_findings_returns_l0(self):
        phase = Phase2VulnAnalysis(rubrics=["injection"])
        from agent.shannon.pipeline import ReconReport
        recon = ReconReport(target="clean-target")
        vuln = phase.run(recon)
        assert vuln.verdict == VerdictLevel.L0

    def test_findings_with_endpoints_score_injection(self):
        from agent.shannon.pipeline import ReconReport
        recon = ReconReport(
            target="api-svc",
            surface_map={"endpoints": ["/api/v1"], "entry_points": ["api-svc"]},
        )
        phase = Phase2VulnAnalysis(rubrics=["injection"])
        vuln = phase.run(recon)
        assert vuln.verdict >= VerdictLevel.L2
        assert len(vuln.findings) > 0

    def test_auth_none_triggers_auth_bypass_l5(self):
        from agent.shannon.pipeline import ReconReport
        recon = ReconReport(
            target="open-svc",
            surface_map={"auth_mechanisms": ["none"]},
        )
        phase = Phase2VulnAnalysis(rubrics=["auth_bypass"])
        vuln = phase.run(recon)
        assert vuln.verdict == VerdictLevel.L5

    def test_extra_findings_merged(self):
        from agent.shannon.pipeline import ReconReport
        recon = ReconReport(target="svc")
        extra = [{"rubric": "manual", "score": 3, "detail": "manual finding"}]
        phase = Phase2VulnAnalysis(rubrics=[])
        vuln = phase.run(recon, extra_findings=extra)
        assert any(f["rubric"] == "manual" for f in vuln.findings)

    def test_rubric_scores_present_in_report(self):
        from agent.shannon.pipeline import ReconReport
        recon = ReconReport(target="svc")
        phase = Phase2VulnAnalysis(rubrics=["injection", "supply_chain"])
        vuln = phase.run(recon)
        assert "injection" in vuln.rubrics
        assert "supply_chain" in vuln.rubrics


# ---------------------------------------------------------------------------
# Fase 3 — Execution (gate)
# ---------------------------------------------------------------------------

class TestPhase3Execution:
    def _make_recon(self):
        from agent.shannon.pipeline import ReconReport
        return ReconReport(target="svc")

    def _make_vuln(self, verdict: VerdictLevel):
        from agent.shannon.pipeline import VulnReport
        return VulnReport(verdict=verdict)

    def test_gate_blocks_execution_below_threshold(self):
        phase = Phase3Execution(gate_threshold=VerdictLevel.L2)
        exec_report = phase.run(self._make_recon(), self._make_vuln(VerdictLevel.L1))
        assert not exec_report.ran
        assert not exec_report.gate_passed
        assert len(exec_report.artifacts) == 0

    def test_gate_allows_execution_at_threshold(self):
        phase = Phase3Execution(gate_threshold=VerdictLevel.L2)
        exec_report = phase.run(self._make_recon(), self._make_vuln(VerdictLevel.L2))
        assert exec_report.ran
        assert exec_report.gate_passed

    def test_gate_allows_execution_above_threshold(self):
        phase = Phase3Execution(gate_threshold=VerdictLevel.L2)
        exec_report = phase.run(self._make_recon(), self._make_vuln(VerdictLevel.L5))
        assert exec_report.ran

    def test_custom_executor_called(self):
        called: list[bool] = []

        def custom_executor(recon, vuln):
            called.append(True)
            return [{"artifact": "custom"}]

        phase = Phase3Execution(gate_threshold=VerdictLevel.L0, executor=custom_executor)
        exec_report = phase.run(self._make_recon(), self._make_vuln(VerdictLevel.L0))
        assert called
        assert exec_report.artifacts == [{"artifact": "custom"}]

    def test_gate_reason_present_when_blocked(self):
        phase = Phase3Execution(gate_threshold=VerdictLevel.L4)
        exec_report = phase.run(self._make_recon(), self._make_vuln(VerdictLevel.L1))
        assert "below" in exec_report.gate_reason.lower()


# ---------------------------------------------------------------------------
# Fase 4 — Reporting
# ---------------------------------------------------------------------------

class TestPhase4Reporting:
    def _build_reports(self, verdict=VerdictLevel.L3, ran=True, artifacts=None):
        from agent.shannon.pipeline import (
            ReconReport,
            VulnReport,
            ExecutionReport,
        )
        recon = ReconReport(target="svc", surface_map={"endpoints": ["/api"]})
        findings = [{"rubric": "injection", "score": 3}] if verdict >= VerdictLevel.L2 else []
        vuln = VulnReport(verdict=verdict, findings=findings, rubrics={"injection": 3})
        exec_report = ExecutionReport(
            ran=ran,
            gate_passed=ran,
            gate_reason="ok" if ran else "blocked",
            artifacts=artifacts or ([{"ev": 1}] if ran else []),
        )
        return recon, vuln, exec_report

    def test_report_has_exploit_when_artifacts_present(self):
        recon, vuln, exec_report = self._build_reports(ran=True, artifacts=[{"x": 1}])
        phase = Phase4Reporting()
        report = phase.run(recon, vuln, exec_report)
        assert report.has_exploit is True

    def test_no_exploit_when_gate_blocked(self):
        recon, vuln, exec_report = self._build_reports(ran=False, artifacts=[])
        phase = Phase4Reporting()
        report = phase.run(recon, vuln, exec_report)
        assert report.has_exploit is False

    def test_report_title_contains_verdict_and_target(self):
        recon, vuln, exec_report = self._build_reports(verdict=VerdictLevel.L3)
        phase = Phase4Reporting()
        report = phase.run(recon, vuln, exec_report)
        assert "L3" in report.title
        assert "svc" in report.title

    def test_evidence_has_3_phases(self):
        recon, vuln, exec_report = self._build_reports()
        phase = Phase4Reporting()
        report = phase.run(recon, vuln, exec_report)
        phase_names = {e["phase"] for e in report.evidence}
        assert "recon" in phase_names
        assert "vuln_analysis" in phase_names
        assert "execution" in phase_names

    def test_verdict_propagated(self):
        recon, vuln, exec_report = self._build_reports(verdict=VerdictLevel.L5)
        phase = Phase4Reporting()
        report = phase.run(recon, vuln, exec_report)
        assert report.verdict == VerdictLevel.L5


# ---------------------------------------------------------------------------
# AdversarialPipeline — integração end-to-end
# ---------------------------------------------------------------------------

class TestAdversarialPipeline:
    def test_pipeline_runs_all_4_phases(self):
        pipeline = AdversarialPipeline()
        result = pipeline.run("integration-target")
        assert result.recon is not None
        assert result.vuln is not None
        assert result.execution is not None
        assert result.report is not None
        assert result.success is True

    def test_pipeline_with_high_risk_context_produces_findings(self):
        pipeline = AdversarialPipeline(
            recon=Phase1Recon(depth=3),
            vuln=Phase2VulnAnalysis(),
        )
        result = pipeline.run(
            "risky-target",
            context={
                "endpoints": ["/api/v1", "/admin"],
                "permissions": ["root"],
                "auth_mechanisms": ["none"],
            },
        )
        assert result.success
        assert result.vuln.verdict >= VerdictLevel.L4
        assert len(result.vuln.findings) > 0

    def test_pipeline_gate_blocks_execution_for_low_verdict(self):
        pipeline = AdversarialPipeline(
            vuln=Phase2VulnAnalysis(rubrics=[]),  # sem rubricas → L0
            execution=Phase3Execution(gate_threshold=VerdictLevel.L2),
        )
        result = pipeline.run("safe-target")
        assert result.execution is not None
        assert result.execution.ran is False

    def test_pipeline_no_exploit_no_report_for_clean_target(self):
        pipeline = AdversarialPipeline(
            vuln=Phase2VulnAnalysis(rubrics=[]),
        )
        result = pipeline.run("clean-target")
        assert result.report is not None
        assert result.report.has_exploit is False

    def test_pipeline_result_has_total_elapsed(self):
        pipeline = AdversarialPipeline()
        result = pipeline.run("target")
        assert result.total_elapsed_ms >= 0

    def test_pipeline_success_false_on_exception(self):
        class BrokenRecon(Phase1Recon):
            def run(self, target, context=None):
                raise RuntimeError("recon failed")

        pipeline = AdversarialPipeline(recon=BrokenRecon())
        result = pipeline.run("broken-target")
        assert result.success is False
        assert "recon failed" in result.error

    def test_pipeline_with_extra_findings_from_external_scanner(self):
        pipeline = AdversarialPipeline()
        extra = [{"rubric": "external_scanner", "score": 4, "target": "svc", "detail": "CVE-2024-XXXX"}]
        result = pipeline.run("svc", extra_findings=extra)
        assert result.success
        assert any(f.get("rubric") == "external_scanner" for f in result.vuln.findings)

    def test_verdict_router_l0_to_l6_coverage(self):
        """Garante que todos os níveis L0–L6 são instanciáveis e ordenáveis."""
        levels = list(VerdictLevel)
        assert len(levels) == 7
        assert levels[0] == VerdictLevel.L0
        assert levels[-1] == VerdictLevel.L6
        assert VerdictLevel.L3 > VerdictLevel.L2
        assert VerdictLevel.L5 < VerdictLevel.L6
