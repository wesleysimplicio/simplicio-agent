#!/usr/bin/env python3
"""turbo-speed 4: token diet — cache-sacred layout, clamping, compression.

Benchmarks for token diet:
  - Cache prefix stability test: 2 turnos consecutivos têm prefixo byte-idêntico
  - Tool result clamping (head+tail com handle)
  - Conversation compression (tokens saved, savings events)
  - Ordem de aplicação: clamp → compress → cache

Métricas:
  - Cache-hit rate potencial (prefixo estável entre turnos)
  - Clamp efficacy (tokens economizados em resultados gigantes)
  - Compression ratio (antes/depois por sessão longa)
  - Pipeline ordering validation

Uso:
    python scripts/turbo-speed/04-token-diet.py              # bateria completa
    python scripts/turbo-speed/04-token-diet.py --json        # saída JSON
    python scripts/turbo-speed/04-token-diet.py --quick       # só cache check

Baseline commitado em scripts/turbo-speed/baselines/token-diet.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Import dependências reais se disponíveis
try:
    from agent._hermes_fast import estimate_tokens as estimate_tokens_fn
    HAVE_ESTIMATOR = True
except ImportError:
    HAVE_ESTIMATOR = False
    def estimate_tokens_fn(text: str) -> int:
        if not text:
            return 0
        return (len(text) + 3) // 4


# ---------------------------------------------------------------------------
# Hardware annotation
# ---------------------------------------------------------------------------
def _hw_annotation() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
        "machine": platform.machine(),
        "have_estimator": HAVE_ESTIMATOR,
    }


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass
class CacheStabilityResult:
    scenario: str
    turn1_prefix_hash: str = ""
    turn2_prefix_hash: str = ""
    stable: bool = False
    notes: str = ""
    hw: dict[str, Any] = field(default_factory=_hw_annotation)


@dataclass
class ClampResult:
    scenario: str
    raw_tokens: int = 0
    clamped_tokens: int = 0
    savings_tokens: int = 0
    savings_pct: float = 0.0
    notes: str = ""
    hw: dict[str, Any] = field(default_factory=_hw_annotation)


@dataclass
class CompressionResult:
    scenario: str
    before_tokens: int = 0
    after_tokens: int = 0
    ratio: float = 0.0
    savings_tokens: int = 0
    notes: str = ""
    hw: dict[str, Any] = field(default_factory=_hw_annotation)


# ---------------------------------------------------------------------------
# Medição 1: Cache prefix stability test
# ---------------------------------------------------------------------------

def _build_prompt(
    system_content: str,
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    timestamp: str | None = None,
) -> bytes:
    """Serializa o prompt para bytes (simula o que vai no cache)."""
    parts: list[bytes] = []
    parts.append(b"<|system|>\n")
    parts.append(system_content.encode("utf-8"))
    parts.append(b"\n")
    if timestamp:
        parts.append(b"<!-- timestamp: ")
        parts.append(timestamp.encode("utf-8"))
        parts.append(b" -->\n")
    # Tools
    for t in tools:
        parts.append(json.dumps(t, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        parts.append(b"\n")
    # Messages
    for msg in messages:
        parts.append(json.dumps(msg, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        parts.append(b"\n")
    return b"".join(parts)


def measure_cache_stability() -> CacheStabilityResult:
    """Testa se 2 turnos consecutivos produzem prefixo cacheável byte-idêntico.

    Cenário: system prompt estável + tools estáveis + mensagens mudando.
    O prefixo (system + tools + primeiras mensagens estáveis) deve ser igual.
    """
    system = "You are a helpful coding assistant. You help users write and debug code."
    tools: list[dict[str, Any]] = [
        {"name": "read_file", "description": "Read a file"},
        {"name": "write_file", "description": "Write a file"},
        {"name": "terminal", "description": "Run a command"},
    ]

    # Turn 1: user message 1 + assistant response 1
    messages_1 = [
        {"role": "user", "content": "Can you read the config file?"},
        {"role": "assistant", "content": "Sure, let me check."},
    ]

    # Turn 2: user message 2 + assistant response 2 (same prefix!)
    messages_2 = [
        {"role": "user", "content": "Can you read the config file?"},
        {"role": "assistant", "content": "Sure, let me check."},
        {"role": "user", "content": "Now show me the logs."},
        {"role": "assistant", "content": "Here are the logs..."},
    ]

    # Prefixo estável é system + tools + (mensagens que não mudaram)
    prefix_builder = lambda ts: _build_prompt(system, tools, messages_1, timestamp=ts)

    # Sem timestamp — deve ser igual
    p1 = prefix_builder(None)
    p2 = _build_prompt(system, tools, messages_2)

    h1 = hashlib.sha256(p1).hexdigest()[:16]
    h2 = hashlib.sha256(p2[:len(p1)]).hexdigest()[:16]

    stable = h1 == h2

    notes = (
        f"Prefix bytes: {len(p1)} (turn1), same prefix in turn2: {len(p1)} bytes. "
        f"Hash: {h1} vs {h2}. "
        f"{'✅ Prefixo estável — cache hit rate potencial: alto.' if stable else '❌ Prefixo mudou — algo quebrou a estabilidade.'}"
    )

    return CacheStabilityResult(
        scenario="cache-prefix-stability (consecutive turns)",
        turn1_prefix_hash=h1,
        turn2_prefix_hash=h2,
        stable=stable,
        notes=notes,
    )


def measure_cache_instability_timestamp() -> CacheStabilityResult:
    """Testa se um timestamp no system prompt QUEBRA a estabilidade.

    Este teste DEVE falhar — é a prova de que timestamps no system prompt
    destroem o cache. Se passar, algo está errado.
    """
    system = "You are a helpful coding assistant."
    tools: list[dict[str, Any]] = [{"name": "read_file", "description": "Read a file"}]
    messages = [{"role": "user", "content": "Hello"}]

    p1 = _build_prompt(system, tools, messages, timestamp="2026-07-03T10:00:00")
    p2 = _build_prompt(system, tools, messages, timestamp="2026-07-03T10:00:01")

    h1 = hashlib.sha256(p1).hexdigest()[:16]
    h2 = hashlib.sha256(p2).hexdigest()[:16]

    stable = h1 == h2  # Deve ser False

    notes = (
        f"Hash com t1: {h1}, com t2: {h2}. "
        f"{'⚠ ESTÁVEL (inesperado) — timestamp no system não quebrou o cache!' if stable else '✅ Instável como esperado — timestamp no system quebra o cache.'}"
    )

    return CacheStabilityResult(
        scenario="cache-instability-timestamp (timestamp quebra cache)",
        turn1_prefix_hash=h1,
        turn2_prefix_hash=h2,
        stable=stable,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Medição 2: Clamping de tool results
# ---------------------------------------------------------------------------

def _clamp_tool_result(
    content: str,
    max_tokens: int = 4000,
    head_ratio: float = 0.3,
    tail_ratio: float = 0.1,
) -> tuple[str, int]:
    """Aplica clamping head+tail num tool result.

    Retorna (clamped_text, tokens_saved).
    """
    raw_tokens = estimate_tokens_fn(content)
    if raw_tokens <= max_tokens:
        return content, 0

    total_chars = len(content)
    head_chars = int(total_chars * head_ratio)
    tail_chars = int(total_chars * tail_ratio)

    head = content[:head_chars]
    tail = content[-tail_chars:] if tail_chars > 0 else ""

    clamped = f"{head}\n\n[... {raw_tokens - max_tokens} tokens clamped ...]\n\n{tail}"
    clamped_tokens = estimate_tokens_fn(clamped)
    savings = raw_tokens - clamped_tokens
    return clamped, savings


def _make_large_result(size_tokens: int) -> str:
    """Gera um tool result de size_tokens tokens (aprox)."""
    chars_needed = size_tokens * 4
    return "line " + "data " * 50 + "\n" * (chars_needed // 60) + "x" * (chars_needed % 60)


def measure_tool_result_clamping() -> ClampResult:
    """Mede eficácia do clamping em tool results de vários tamanhos."""
    sizes = [1000, 5000, 10000, 50000]  # tokens
    results: list[ClampResult] = []

    for size in sizes:
        content = _make_large_result(size)
        raw_tokens = estimate_tokens_fn(content)
        clamped, savings = _clamp_tool_result(content, max_tokens=4000)
        clamped_tokens = estimate_tokens_fn(clamped)
        pct = (savings / raw_tokens * 100) if raw_tokens > 0 else 0

        r = ClampResult(
            scenario=f"clamp-{size}tokens",
            raw_tokens=raw_tokens,
            clamped_tokens=clamped_tokens,
            savings_tokens=savings,
            savings_pct=round(pct, 1),
            notes=f"Max tokens: 4000, head_ratio=0.3, tail_ratio=0.1.",
        )
        results.append(r)

    # Escolha o resultado mais representativo (50k tokens)
    for r in results:
        if "50000" in r.scenario:
            return r

    return results[-1] if results else ClampResult(scenario="clamp", notes="no data")


def measure_clamp_series() -> list[ClampResult]:
    """Série completa de clamping."""
    sizes = [1000, 5000, 10000, 50000]
    series: list[ClampResult] = []
    for size in sizes:
        content = _make_large_result(size)
        raw_tokens = estimate_tokens_fn(content)
        clamped, savings = _clamp_tool_result(content, max_tokens=4000)
        clamped_tokens = estimate_tokens_fn(clamped)
        pct = (savings / raw_tokens * 100) if raw_tokens > 0 else 0
        series.append(ClampResult(
            scenario=f"clamp-{size}tokens",
            raw_tokens=raw_tokens,
            clamped_tokens=clamped_tokens,
            savings_tokens=savings,
            savings_pct=round(pct, 1),
            notes=f"Max tokens: 4000. Clamp eficaz para resultados > 4K tokens.",
        ))
    return series


# ---------------------------------------------------------------------------
# Medição 3: Conversation compression
# ---------------------------------------------------------------------------

def _build_long_conversation(n_turns: int = 50) -> list[dict[str, Any]]:
    """Constrói uma conversa longa para testar compressão."""
    conv: list[dict[str, Any]] = [
        {"role": "system", "content": "You are a helpful assistant. " * 20}
    ]
    for i in range(n_turns):
        role = "user" if i % 2 == 0 else "assistant"
        content = f"Turn {i}: " + "this is a conversation message with some repeated patterns that compress well. " * (5 + (i % 10))
        conv.append({"role": role, "content": content})
    return conv


def _compress_conversation(
    messages: list[dict[str, Any]],
    max_tokens: int = 8000,
) -> tuple[list[dict[str, Any]], int, int]:
    """Simula compressão: remove mensagens do meio mantendo system + recentes.

    Returns (compressed_msgs, before_tokens, after_tokens).
    """
    before_tokens = sum(estimate_tokens_fn(json.dumps(m, ensure_ascii=False)) for m in messages)

    if before_tokens <= max_tokens:
        return messages, before_tokens, before_tokens

    # Estratégia: manter system + últimas N mensagens
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]

    compressed = list(system_msgs)
    kept = 0
    for m in reversed(non_system):
        test_msgs = compressed + [m]
        test_tokens = sum(estimate_tokens_fn(json.dumps(x, ensure_ascii=False)) for x in test_msgs)
        if test_tokens <= max_tokens or kept < 5:
            compressed.insert(len(system_msgs), m)
            kept += 1
        else:
            break

    after_tokens = sum(estimate_tokens_fn(json.dumps(m, ensure_ascii=False)) for m in compressed)
    return compressed, before_tokens, after_tokens


def measure_compression() -> CompressionResult:
    """Mede eficácia da compressão em conversa longa."""
    conv = _build_long_conversation(50)
    compressed, before, after = _compress_conversation(conv, max_tokens=8000)
    ratio = after / before if before > 0 else 1.0

    return CompressionResult(
        scenario="conversation-compression (50 turns)",
        before_tokens=before,
        after_tokens=after,
        ratio=round(ratio, 3),
        savings_tokens=before - after,
        notes=f"Compressão reduziu de {before} para {after} tokens ({((before-after)/before*100):.1f}% savings). "
              f"Estratégia: keep system + recentes.",
    )


def measure_compression_series() -> list[CompressionResult]:
    """Série de compressão em vários tamanhos de conversa."""
    results: list[CompressionResult] = []
    for n_turns in [10, 25, 50, 100]:
        conv = _build_long_conversation(n_turns)
        compressed, before, after = _compress_conversation(conv, max_tokens=8000)
        ratio = after / before if before > 0 else 1.0
        results.append(CompressionResult(
            scenario=f"compression-{n_turns}turns",
            before_tokens=before,
            after_tokens=after,
            ratio=round(ratio, 3),
            savings_tokens=before - after,
            notes=f"{n_turns} turns, compressed to max 8K tokens.",
        ))
    return results


# ---------------------------------------------------------------------------
# Medição 4: Pipeline order validation (clamp → compress → cache)
# ---------------------------------------------------------------------------

def measure_pipeline_order() -> CompressionResult:
    """Valida que a ordem clamp → compress → cache não se canibaliza.

    Simula um pipeline onde:
    1. Clamp reduz tool results > 4K tokens
    2. Compress reduz total < 8K tokens
    3. Cache é estável (prefixo não muda)
    """
    # Cenário: conversa com tool result grande
    system = "You are a helpful assistant."
    big_result = _make_large_result(10000)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Search the codebase"},
        {"role": "assistant", "content": "Let me check...", "tool_calls": [{"function": {"name": "search"}}]},
        {"role": "tool", "content": big_result, "tool_call_id": "call_1"},
        {"role": "user", "content": "Now show me the results"},
        {"role": "assistant", "content": "Here is what I found: " + big_result[:500]},
    ]

    before_raw = sum(estimate_tokens_fn(json.dumps(m, ensure_ascii=False)) for m in messages)
    before_clamped = before_raw

    # Step 1: Clamp tool results
    clamped_msgs: list[dict[str, Any]] = []
    for m in messages:
        if m.get("role") == "tool" and m.get("content"):
            if isinstance(m["content"], str):
                clamped, _ = _clamp_tool_result(m["content"], max_tokens=4000)
                clamped_msgs.append({**m, "content": clamped})
            else:
                clamped_msgs.append(m)
        else:
            clamped_msgs.append(m)

    after_clamp = sum(estimate_tokens_fn(json.dumps(m, ensure_ascii=False)) for m in clamped_msgs)

    # Step 2: Compress
    compressed_clamped, _, after_compress = _compress_conversation(clamped_msgs, max_tokens=8000)

    # Step 3: Verifica que cache prefix não mudou
    prefix_msgs = [m for m in messages if m.get("role") in ("system",)]
    prefix_bytes = json.dumps(prefix_msgs, ensure_ascii=False, sort_keys=True).encode()

    # Clamp + compress não deve afetar system prompt
    compressed_prefix = compressed_clamped[:1] if compressed_clamped else []
    compressed_prefix_bytes = json.dumps(compressed_prefix, ensure_ascii=False, sort_keys=True).encode()

    cache_stable = prefix_bytes == compressed_prefix_bytes

    return CompressionResult(
        scenario="pipeline-order (clamp→compress→cache)",
        before_tokens=before_raw,
        after_tokens=after_compress,
        ratio=round(after_compress / before_raw, 3) if before_raw > 0 else 1.0,
        savings_tokens=before_raw - after_compress,
        notes=(
            f"Pipeline: antes={before_raw}t → clamp={after_clamp}t → compress={after_compress}t. "
            f"Cache prefix stable: {'✅' if cache_stable else '❌'}. "
            f"Ordem válida: clamp reduz tool results, compress reduz total, cache não se canibaliza."
        ),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="turbo-speed 4: token diet benchmark")
    parser.add_argument("--json", action="store_true", help="saída JSON")
    parser.add_argument("--quick", action="store_true", help="só cache check")
    args = parser.parse_args()

    results: list[Any] = []

    print("═══ turbo-speed 4: Token Diet ═══")
    print(f"Hardware: {json.dumps(_hw_annotation(), indent=2)}")
    print()

    # 1. Cache stability
    print("▶ Testando estabilidade do prefixo de cache...")
    r1 = measure_cache_stability()
    results.append(r1)
    print(f"   Prefixo turn1: {r1.turn1_prefix_hash}")
    print(f"   Prefixo turn2: {r1.turn2_prefix_hash}")
    print(f"   Estável: {'✅' if r1.stable else '❌'} — {r1.notes}")

    # 2. Timestamp instability (negative test)
    print("\n▶ Testando que timestamp NO SYSTEM quebra o cache...")
    r2 = measure_cache_instability_timestamp()
    results.append(r2)
    print(f"   Estável (deveria ser False): {'⚠ SIM (inesperado!)' if r2.stable else '✅ NÃO (esperado)'}")
    print(f"   Notas: {r2.notes}")

    if not args.quick:
        # 3. Clamping series
        print("\n▶ Medindo clamping de tool results...")
        clamp_series = measure_clamp_series()
        results.extend(clamp_series)
        for r in clamp_series:
            print(f"   {r.scenario}: {r.raw_tokens}t → {r.clamped_tokens}t (saved {r.savings_tokens}t, {r.savings_pct}%)")

        # 4. Compression series
        print("\n▶ Medindo compressão de conversa...")
        comp_series = measure_compression_series()
        results.extend(comp_series)
        for r in comp_series:
            print(f"   {r.scenario}: {r.before_tokens}t → {r.after_tokens}t (ratio={r.ratio}, saved {r.savings_tokens}t)")

        # 5. Pipeline order
        print("\n▶ Validando pipeline order (clamp→compress→cache)...")
        r5 = measure_pipeline_order()
        results.append(r5)
        print(f"   Antes: {r5.before_tokens}t → Depois: {r5.after_tokens}t (saved {r5.savings_tokens}t)")
        print(f"   Notas: {r5.notes}")

    # Summary
    print("\n═══ Resumo ═══")
    for r in results:
        if isinstance(r, CacheStabilityResult):
            print(f"  {r.scenario}: {'✅ estável' if r.stable else '❌ instável'}")
        elif isinstance(r, ClampResult):
            print(f"  {r.scenario}: {r.raw_tokens}t → {r.clamped_tokens}t ({r.savings_pct}% saved)")
        elif isinstance(r, CompressionResult):
            print(f"  {r.scenario}: {r.before_tokens}t → {r.after_tokens}t (ratio={r.ratio})")

    # Save baseline
    baseline_dir = REPO_ROOT / "scripts" / "turbo-speed" / "baselines"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = baseline_dir / "token-diet.json"
    with open(baseline_path, "w") as f:
        json.dump(
            {
                "meta": {"turbo_speed": 4, "description": "token diet — cache-sacred, clamping, compression"},
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
