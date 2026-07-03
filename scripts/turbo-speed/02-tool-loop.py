#!/usr/bin/env python3
"""turbo-speed 2: tool-loop — execução paralela, streaming dispatch, connection pooling.

Benchmarks for the agent's tool execution loop:
  - Sequential vs parallel tool execution (wall-clock comparison)
  - Early dispatch during streaming (tool starts before model finishes)
  - Connection pooling overhead (single reused client vs new-per-call)
  - Mixed mutate/read-only safety

Métricas:
  - Wall-clock speedup: sequential vs parallel for N read-only tools
  - Dispatch latency saved by early streaming dispatch
  - Handshake savings from connection pooling

Uso:
    python scripts/turbo-speed/02-tool-loop.py              # bateria completa
    python scripts/turbo-speed/02-tool-loop.py --json        # saída JSON
    python scripts/turbo-speed/02-tool-loop.py --quick       # só paralelo

Baseline commitado em scripts/turbo-speed/baselines/tool-loop.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Awaitable

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Hardware annotation
# ---------------------------------------------------------------------------
def _hw_annotation() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
    }


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass
class ToolLoopResult:
    scenario: str
    sequential_s: float = 0.0
    parallel_s: float = 0.0
    speedup: float = 0.0
    notes: str = ""
    hw: dict[str, Any] = field(default_factory=_hw_annotation)


@dataclass
class ConnectionPoolResult:
    scenario: str
    new_client_s: float = 0.0
    pooled_client_s: float = 0.0
    handshake_savings: float = 0.0
    notes: str = ""
    hw: dict[str, Any] = field(default_factory=_hw_annotation)


# ---------------------------------------------------------------------------
# Simulated tool calls (no real I/O — pure asyncio.sleep for timing)
# ---------------------------------------------------------------------------

async def _tool_read_only(name: str, delay: float = 0.1) -> dict[str, Any]:
    """Simula uma tool read-only (ex.: read_file, search)."""
    await asyncio.sleep(delay)
    return {"tool": name, "status": "ok", "read_only": True}


async def _tool_mutate(name: str, delay: float = 0.15) -> dict[str, Any]:
    """Simula uma tool mutante (ex.: write_file, patch)."""
    await asyncio.sleep(delay)
    return {"tool": name, "status": "ok", "mutate": True}


CLASSIFIED_TOOLS: dict[str, bool] = {
    "read_file": True,      # True = read-only
    "search_files": True,
    "terminal_read": True,
    "write_file": False,    # False = mutate
    "patch": False,
    "terminal_write": False,
}


def _classify(names: list[str]) -> tuple[list[str], list[str]]:
    """Separa tools em read-only e mutate."""
    ro = [n for n in names if CLASSIFIED_TOOLS.get(n, True)]
    mut = [n for n in names if not CLASSIFIED_TOOLS.get(n, True)]
    return ro, mut


# ---------------------------------------------------------------------------
# Medição 1: Sequential vs Parallel execution
# ---------------------------------------------------------------------------

async def _sequential_run(tools: list[tuple[str, float]]) -> float:
    """Executa tools uma após a outra. Retorna wall-clock total."""
    start = time.perf_counter()
    for name, delay in tools:
        if CLASSIFIED_TOOLS.get(name, True):
            await _tool_read_only(name, delay)
        else:
            await _tool_mutate(name, delay)
    return time.perf_counter() - start


async def _parallel_run(tools: list[tuple[str, float]]) -> tuple[float, str]:
    """Executa tools em paralelo. Mutantes serializam, read-only paraleliza."""
    start = time.perf_counter()
    ro_tools = [(n, d) for n, d in tools if CLASSIFIED_TOOLS.get(n, True)]
    mut_tools = [(n, d) for n, d in tools if not CLASSIFIED_TOOLS.get(n, True)]

    # Read-only vão em paralelo
    async def _run_one(name: str, delay: float) -> Any:
        return await _tool_read_only(name, delay)

    tasks = [_run_one(n, d) for n, d in ro_tools]

    # Mutantes vão em série (depois dos read-only)
    # (Simulamos política de segurança: mutante serializa)
    async def _run_mut_serially() -> None:
        for name, delay in mut_tools:
            await _tool_mutate(name, delay)

    if mut_tools:
        tasks.append(_run_mut_serially())

    if tasks:
        await asyncio.gather(*tasks)

    elapsed = time.perf_counter() - start
    status = "all_parallel" if not mut_tools else "ro_parallel_mut_serial"
    return elapsed, status


def measure_parallel_speedup(
    n_tools: int = 8,
    read_only_ratio: float = 0.75,
    base_delay: float = 0.1,
) -> ToolLoopResult:
    """Mede speedup da execução paralela vs sequencial."""
    import random
    random.seed(42)

    tools: list[tuple[str, float]] = []
    tool_names = list(CLASSIFIED_TOOLS.keys())
    for i in range(n_tools):
        name = tool_names[i % len(tool_names)]
        jitter = random.uniform(0.8, 1.2)
        delay = base_delay * jitter
        tools.append((name, delay))

    # Sequential
    seq_time = asyncio.run(_sequential_run(tools))

    # Parallel
    par_time, status = asyncio.run(_parallel_run(tools))

    speedup = seq_time / par_time if par_time > 0 else 0.0

    notes = (
        f"{n_tools} tools ({int(n_tools*read_only_ratio)} RO, {n_tools - int(n_tools*read_only_ratio)} mut), "
        f"base_delay={base_delay}s, policy={status}"
    )

    return ToolLoopResult(
        scenario=f"parallel-speedup (n={n_tools})",
        sequential_s=round(seq_time, 4),
        parallel_s=round(par_time, 4),
        speedup=round(speedup, 2),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Medição 2: Early dispatch simulation
# ---------------------------------------------------------------------------

def measure_early_dispatch() -> ToolLoopResult:
    """Simula early dispatch vs wait-for-complete.

    Early: tool começa a executar assim que parseada (delay simulado de geração).
    Wait: tool só começa depois do modelo terminar a mensagem inteira.
    """
    gen_time = 0.3  # Tempo simulado de geração do resto da mensagem
    tool_delay = 0.2  # Tempo simulado de execução da tool

    # Wait: modelo termina -> executa tool
    wait_time = gen_time + tool_delay

    # Early: execução começa durante a geração
    # Se tool_delay <= gen_time, a tool termina antes do modelo
    early_time = max(gen_time, tool_delay)

    savings = (wait_time - early_time) / wait_time * 100 if wait_time > 0 else 0

    return ToolLoopResult(
        scenario="early-dispatch-vs-wait",
        sequential_s=round(wait_time, 3),
        parallel_s=round(early_time, 3),
        speedup=round(wait_time / early_time, 2) if early_time > 0 else 0,
        notes=(
            f"Geração simulada: {gen_time}s, tool delay: {tool_delay}s. "
            f"Early dispatch corta {savings:.0f}% da latência percebida."
        ),
    )


# ---------------------------------------------------------------------------
# Medição 3: Connection pooling (simulado)
# ---------------------------------------------------------------------------

class _FakeHTTPClient:
    """Simula um cliente HTTP com handshake."""

    def __init__(self, name: str = "pooled"):
        self.name = name
        self._connected = False

    async def connect(self) -> float:
        """Simula handshake TLS. Primeira vez é caro."""
        if self._connected:
            return 0.001  # Já conectado: ~1ms
        await asyncio.sleep(0.05)  # Handshake: ~50ms
        self._connected = True
        return 0.05

    async def request(self, _path: str) -> dict[str, Any]:
        await self.connect()
        await asyncio.sleep(0.02)  # Request time
        return {"status": "ok"}


def measure_connection_pooling(n_requests: int = 10) -> ConnectionPoolResult:
    """Compara new-client-per-request vs pooled-client."""

    async def _new_client_each() -> float:
        start = time.perf_counter()
        for _ in range(n_requests):
            c = _FakeHTTPClient("new")
            await c.request("/api/chat")
        return time.perf_counter() - start

    async def _pooled_client() -> float:
        start = time.perf_counter()
        c = _FakeHTTPClient("pooled")
        for _ in range(n_requests):
            await c.request("/api/chat")
        return time.perf_counter() - start

    new_time = asyncio.run(_new_client_each())
    pooled_time = asyncio.run(_pooled_client())

    return ConnectionPoolResult(
        scenario=f"connection-pooling ({n_requests} requests)",
        new_client_s=round(new_time, 4),
        pooled_client_s=round(pooled_time, 4),
        handshake_savings=round((new_time - pooled_time) / new_time * 100, 1) if new_time > 0 else 0,
        notes=f"Pooled evita {n_requests - 1} handshakes TLS. Savings grow with request count.",
    )


# ---------------------------------------------------------------------------
# Medição 4: Prewarm no boot
# ---------------------------------------------------------------------------

def measure_prewarm() -> ConnectionPoolResult:
    """Mede quanto o prewarm (abrir conexão no boot) economiza na primeira msg."""

    async def _no_prewarm() -> float:
        start = time.perf_counter()
        c = _FakeHTTPClient("no_prewarm")
        await c.request("/api/chat/first")
        return time.perf_counter() - start

    async def _with_prewarm() -> float:
        # Prewarm: conexão aberta durante o boot
        c = _FakeHTTPClient("prewarmed")
        await c.connect()
        # Primeira mensagem real
        start = time.perf_counter()
        await c.request("/api/chat/first")
        return time.perf_counter() - start

    no_prewarm = asyncio.run(_no_prewarm())
    with_prewarm = asyncio.run(_with_prewarm())

    return ConnectionPoolResult(
        scenario="prewarm-first-message",
        new_client_s=round(no_prewarm, 4),
        pooled_client_s=round(with_prewarm, 4),
        handshake_savings=round((no_prewarm - with_prewarm) / no_prewarm * 100, 1) if no_prewarm > 0 else 0,
        notes=f"Prewarm elimina handshake TLS da primeira mensagem. Economia ~{((no_prewarm-with_prewarm)*1000):.0f}ms.",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="turbo-speed 2: tool-loop benchmark")
    parser.add_argument("--json", action="store_true", help="saída JSON")
    parser.add_argument("--quick", action="store_true", help="só paralelo")
    parser.add_argument("--n-tools", type=int, default=8, help="número de tools")
    args = parser.parse_args()

    results: list[Any] = []

    print("═══ turbo-speed 2: Tool Loop ═══")
    print(f"Hardware: {json.dumps(_hw_annotation(), indent=2)}")
    print()

    # 1. Parallel speedup
    print(f"▶ Medindo speedup paralelo ({args.n_tools} tools)...")
    r1 = measure_parallel_speedup(n_tools=args.n_tools)
    results.append(r1)
    print(f"   Sequential: {r1.sequential_s:.3f}s")
    print(f"   Parallel:   {r1.parallel_s:.3f}s")
    print(f"   Speedup:    {r1.speedup:.2f}x")
    print(f"   Notas: {r1.notes}")

    if not args.quick:
        # 2. Early dispatch
        print("\n▶ Medindo early dispatch...")
        r2 = measure_early_dispatch()
        results.append(r2)
        print(f"   Wait-for-complete: {r2.sequential_s:.3f}s")
        print(f"   Early dispatch:    {r2.parallel_s:.3f}s")
        print(f"   Speedup:           {r2.speedup:.2f}x")
        print(f"   Notas: {r2.notes}")

        # 3. Connection pooling
        print(f"\n▶ Medindo connection pooling (10 requests)...")
        r3 = measure_connection_pooling(10)
        results.append(r3)
        pct = ((r3.new_client_s - r3.pooled_client_s) / r3.new_client_s * 100) if r3.new_client_s > 0 else 0
        print(f"   New client cada: {r3.new_client_s:.4f}s")
        print(f"   Pooled client:   {r3.pooled_client_s:.4f}s")
        print(f"   Economia:        {pct:.1f}%")

        # 4. Prewarm
        print("\n▶ Medindo prewarm no boot...")
        r4 = measure_prewarm()
        results.append(r4)
        savings_ms = (r4.new_client_s - r4.pooled_client_s) * 1000
        print(f"   Sem prewarm:  {r4.new_client_s:.4f}s")
        print(f"   Com prewarm:  {r4.pooled_client_s:.4f}s")
        print(f"   Economia:     {savings_ms:.1f}ms na primeira mensagem")

    # Summary
    print("\n═══ Resumo ═══")
    for r in results:
        if isinstance(r, ToolLoopResult):
            print(f"  {r.scenario}: seq={r.sequential_s:.3f}s, par={r.parallel_s:.3f}s, speedup={r.speedup:.2f}x")
        elif isinstance(r, ConnectionPoolResult):
            print(f"  {r.scenario}: new={r.new_client_s:.4f}s, pooled={r.pooled_client_s:.4f}s, savings={r.handshake_savings:.1f}%")

    # Save baseline
    baseline_dir = REPO_ROOT / "scripts" / "turbo-speed" / "baselines"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = baseline_dir / "tool-loop.json"
    with open(baseline_path, "w") as f:
        json.dump(
            {
                "meta": {"turbo_speed": 2, "description": "tool-loop — parallel execution, streaming dispatch, connection pooling"},
                "hw": _hw_annotation(),
                "results": [asdict(r) for r in results],
            },
            f,
            indent=2,
        )
    print(f"\nBaseline salvo em: {baseline_path}")

    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2, default=str))


if __name__ == "__main__":
    main()
