#!/usr/bin/env python3
"""turbo-speed 1: cold start — lazy imports e TTFP (time-to-first-prompt).

Baselines, mede e valida o cold start do Simplicio Agent vs upstream
NousResearch/hermes-agent.

Métricas:
  - import-time total (sys.modules snapshot)
  - TTFP real: tempo do comando `simplicio-agent --version` e `simplicio-agent chat --yes`
  - Contagem de módulos pesados no boot mínimo
  - Cobertura lazy-import nos gateways/TUI/tools

Uso:
    python scripts/turbo-speed/01-cold-start.py             # bateria completa
    python scripts/turbo-speed/01-cold-start.py --json       # saída JSON
    python scripts/turbo-speed/01-cold-start.py --quick      # só TTFP + módulos

Hardware é anotado no output para reproduzibilidade.
Baseline commitado em scripts/turbo-speed/baselines/cold-start.json.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Pesados que NÃO devem ser importados no boot mínimo
# ---------------------------------------------------------------------------
HEAVY_MODULES = {
    "torch",
    "playwright",
    "selenium",
    "browser",
    "tui",
    "gateway",
    "discord",
    "telegram",
    "slack",
    "whatsapp",
    "computer_use",
    "PIL",
    "cv2",
    "numpy",
}

# ---------------------------------------------------------------------------
# Hardware annotation
# ---------------------------------------------------------------------------
def _hw_annotation() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
        "machine": platform.machine(),
        "node": platform.node(),
        "cpu_count": os.cpu_count(),
    }


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass
class ColdStartResult:
    scenario: str
    import_time_s: float
    ttfp_s: float | None = None
    module_count: int = 0
    heavy_imported: list[str] = field(default_factory=list)
    notes: str = ""
    hw: dict[str, Any] = field(default_factory=_hw_annotation)


# ---------------------------------------------------------------------------
# Medição 1: import-time com sys.modules snapshot
# ---------------------------------------------------------------------------
def measure_import_time(module: str = "hermes_cli") -> ColdStartResult:
    """Mede quanto tempo ``import {module}`` leva e quantos módulos carrega."""
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    wall = time.perf_counter() - start

    # Parse import-time stderr
    heavy_imported: list[str] = []
    for line in proc.stderr.splitlines():
        for h in HEAVY_MODULES:
            if h in line.lower() and "import time" in line:
                heavy_imported.append(line.strip())

    # Module count from stdout
    proc2 = subprocess.run(
        [sys.executable, "-c", f"import {module}; print(len(sys.modules))"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    module_count = int(proc2.stdout.strip()) if proc2.stdout.strip() else 0

    return ColdStartResult(
        scenario=f"import {module}",
        import_time_s=round(wall, 4),
        module_count=module_count,
        heavy_imported=heavy_imported,
        notes=f"Wall-clock inclui subprocess overhead. {len(heavy_imported)} heavy modules detected." if heavy_imported else "No heavy modules in boot.",
        hw=_hw_annotation(),
    )


# ---------------------------------------------------------------------------
# Medição 2: TTFP end-to-end via subprocess version
# ---------------------------------------------------------------------------
def measure_ttfp_version(iterations: int = 5) -> ColdStartResult:
    """Mede TTFP do comando ``simplicio-agent --version`` com subprocess."""
    hermes_bin = REPO_ROOT / "venv/bin/hermes" if (REPO_ROOT / "venv/bin/hermes").exists() else _shutil_which("hermes")
    if not hermes_bin:
        return ColdStartResult(
            scenario="simplicio-agent --version TTFP",
            import_time_s=0.0,
            notes="hermes binary not found in PATH or venv",
            hw=_hw_annotation(),
        )

    times: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        subprocess.run(
            [str(hermes_bin), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        times.append(time.perf_counter() - start)

    median = statistics.median(times)
    return ColdStartResult(
        scenario=f"simplicio-agent --version TTFP (best-of-{iterations})",
        import_time_s=round(median, 4),
        module_count=0,
        notes=f"Raw times: {[round(t, 4) for t in times]}",
        hw=_hw_annotation(),
    )


# ---------------------------------------------------------------------------
# Medição 3: módulos carregados no boot mínimo
# ---------------------------------------------------------------------------
def measure_boot_modules() -> ColdStartResult:
    """Conta e lista módulos carregados num boot mínimo do hermes_cli."""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import hermes_cli; "
            "mods = sorted(sys.modules.keys()); "
            f"heavy = [m for m in mods if any(h in m for h in {sorted(HEAVY_MODULES)})]; "
            "print(f'modules={len(mods)}'); "
            "for h in heavy: print(f'HEAVY:{h}')",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    heavy: list[str] = []
    module_count = 0
    for line in proc.stdout.splitlines():
        if line.startswith("modules="):
            module_count = int(line.split("=")[1])
        elif line.startswith("HEAVY:"):
            heavy.append(line.split(":", 1)[1])

    return ColdStartResult(
        scenario="boot-minimo module audit",
        import_time_s=0.0,
        module_count=module_count,
        heavy_imported=heavy,
        notes="OK" if not heavy else f"WARN: {len(heavy)} heavy modules loaded",
        hw=_hw_annotation(),
    )


# ---------------------------------------------------------------------------
# Medição 4: TTFP do REPL (não-interativo, só boot até prompt)
# ---------------------------------------------------------------------------
def measure_ttfp_repl(iterations: int = 3) -> ColdStartResult:
    """Mede TTFP até o prompt aparecer."""
    hermes_bin = REPO_ROOT / "venv/bin/hermes" if (REPO_ROOT / "venv/bin/hermes").exists() else _shutil_which("hermes")
    if not hermes_bin:
        return ColdStartResult(
            scenario="hermes repl TTFP",
            import_time_s=0.0,
            notes="hermes binary not found",
            hw=_hw_annotation(),
        )

    times: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        proc = subprocess.run(
            [str(hermes_bin), "chat", "--yes"],
            capture_output=True,
            text=True,
            timeout=15,
            input="exit\n",
        )
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    if not times:
        return ColdStartResult(scenario="hermes repl TTFP", import_time_s=0.0, notes="no data")
    median = statistics.median(times)
    return ColdStartResult(
        scenario=f"hermes repl TTFP (best-of-{iterations})",
        import_time_s=round(median, 4),
        notes=f"Raw times: {[round(t, 4) for t in times]}. REPL pode incluir provider handshake.",
        hw=_hw_annotation(),
    )


# ---------------------------------------------------------------------------
# Meta check
# ---------------------------------------------------------------------------
def _check_meta(result: ColdStartResult) -> str:
    """Avalia se o resultado atinge a meta de TTFP < 300ms em --version."""
    if "TTFP" not in result.scenario:
        return ""
    if result.import_time_s <= 0:
        return "N/A"
    if result.import_time_s < 0.3:
        return "META ATINGIDA: TTFP < 300ms"
    return f"⚠ META: TTFP < 300ms (atual: {result.import_time_s*1000:.0f}ms)"


def _shutil_which(cmd: str) -> str | None:
    """Minimal shutil.which replacement."""
    path = os.environ.get("PATH", "")
    for d in path.split(":"):
        full = os.path.join(d, cmd)
        if os.path.isfile(full) and os.access(full, os.X_OK):
            return full
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="turbo-speed 1: cold start benchmark")
    parser.add_argument("--json", action="store_true", help="saída JSON")
    parser.add_argument("--quick", action="store_true", help="só TTFP + módulos")
    args = parser.parse_args()

    results: list[ColdStartResult] = []

    print("═══ turbo-speed 1: Cold Start ═══")
    print(f"Hardware: {json.dumps(_hw_annotation(), indent=2)}")
    print()

    # 1. Import-time
    print("▶ Medindo import-time...")
    r1 = measure_import_time("hermes_cli")
    results.append(r1)
    print(f"   import hermes_cli: {r1.import_time_s:.4f}s, {r1.module_count} módulos")
    if r1.heavy_imported:
        print(f"   ⚠ HEAVY modules: {len(r1.heavy_imported)}")
        for h in r1.heavy_imported[:5]:
            print(f"      {h}")

    if args.quick:
        results.append(measure_boot_modules())
        r = results[-1]
        print(f"   Boot modules: {r.module_count}, heavy: {', '.join(r.heavy_imported) or 'none'}")
    else:
        # 2. TTFP version
        print("▶ Medindo TTFP --version...")
        r2 = measure_ttfp_version(5)
        results.append(r2)
        meta = _check_meta(r2)
        print(f"   --version TTFP: {r2.import_time_s*1000:.1f}ms (best-of-5) {meta}")

        # 3. Boot modules audit
        print("▶ Auditando módulos do boot mínimo...")
        r3 = measure_boot_modules()
        results.append(r3)
        print(f"   Módulos carregados: {r3.module_count}")
        if r3.heavy_imported:
            print(f"   ⚠ Pesados inesperados: {', '.join(r3.heavy_imported)}")
        else:
            print("   ✅ Nenhum módulo pesado no boot (torch, browser, gateway inativo)")

        # 4. TTFP REPL
        print("▶ Medindo TTFP do REPL...")
        r4 = measure_ttfp_repl(3)
        results.append(r4)
        print(f"   REPL boot: {r4.import_time_s*1000:.1f}ms (best-of-3)")
        print(f"   Notas: {r4.notes}")

    # Summary
    print()
    print("═══ Resumo ═══")
    for r in results:
        meta = _check_meta(r)
        print(f"  {r.scenario}: {r.import_time_s*1000:.1f}ms{' ' + meta if meta else ''}")

    # Save baseline
    baseline_dir = REPO_ROOT / "scripts" / "turbo-speed" / "baselines"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = baseline_dir / "cold-start.json"
    with open(baseline_path, "w") as f:
        json.dump(
            {
                "meta": {"turbo_speed": 1, "description": "cold start — lazy imports e TTFP"},
                "hw": _hw_annotation(),
                "results": [asdict(r) for r in results],
            },
            f,
            indent=2,
        )
    print(f"\nBaseline salvo em: {baseline_path}")

    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))


if __name__ == "__main__":
    main()
