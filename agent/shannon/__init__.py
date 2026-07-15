"""Shannon — Adversarial Pipeline (4 fases)."""

from agent.shannon.pipeline import (
    AdversarialPipeline,
    Phase1Recon,
    Phase2VulnAnalysis,
    Phase3Execution,
    Phase4Reporting,
    PipelineResult,
    VerdictLevel,
)

__all__ = [
    "AdversarialPipeline",
    "Phase1Recon",
    "Phase2VulnAnalysis",
    "Phase3Execution",
    "Phase4Reporting",
    "PipelineResult",
    "VerdictLevel",
]
