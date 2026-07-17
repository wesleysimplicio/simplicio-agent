#!/usr/bin/env python3
"""End-to-end-ish benchmark harness for the perf modules ported from
hermes-turbo-agent (see docs/performance.md and docs/SYNC_PIPELINE.md).

Existing numbers in CHANGELOG.md ("2-10x faster JSON") are microbenchmarks
of a single operation. This script measures each perf module against its
own documented fallback, using representative synthetic payloads and no
network calls — so it runs offline and reproducibly in CI.

For modules that expose both a fast path and an explicit fallback function
(fast JSON, fast token estimator), this script calls BOTH the
currently-installed backend AND the fallback implementation directly in the
same process, so you get a real "with extras vs baseline" comparison without
needing two separate virtualenvs. When no fast backend is installed, both
rows measure the same stdlib/naive code path.

Usage:
    python scripts/benchmark_e2e.py                  # human-readable table
    python scripts/benchmark_e2e.py --json            # machine-readable
    python scripts/benchmark_e2e.py --iterations 5000 # more samples
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@dataclass
class Result:
    scenario: str
    variant: str
    ops: int
    total_s: float
    notes: str = ""

    @property
    def per_op_us(self) -> float:
        return (self.total_s / self.ops) * 1_000_000 if self.ops else float("nan")


@dataclass
class Report:
    results: list = field(default_factory=list)

    def add(self, r: Result) -> None:
        self.results.append(r)


def _timeit(fn: Callable[[], Any], iterations: int) -> float:
    start = time.perf_counter()
    for _ in range(iterations):
        fn()
    return time.perf_counter() - start


# ---------------------------------------------------------------------------
# Synthetic payloads
# ---------------------------------------------------------------------------

def _synthetic_transcript(n_messages: int = 24) -> list[dict]:
    """A representative multi-turn transcript: system + alternating
    user/assistant turns, some with tool calls and a large tool result
    (simulating a file read / grep output), roughly what a real agent
    session looks like after a dozen turns."""
    messages = [{"role": "system", "content": "You are a helpful coding assistant." * 20}]
    big_tool_result = json.dumps({"path": "agent/chat_completion_helpers.py", "lines": ["line " + str(i) * 3 for i in range(200)]})
    for i in range(n_messages):
        if i % 4 == 0:
            messages.append({"role": "user", "content": f"Please look at file_{i}.py and explain function {i}."})
        elif i % 4 == 1:
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": f"call_{i}", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": f"file_{i}.py"})}}],
            })
        elif i % 4 == 2:
            messages.append({"role": "tool", "tool_call_id": f"call_{i}", "content": big_tool_result})
        else:
            messages.append({"role": "assistant", "content": f"Function {i} does X, Y, and Z. Here is a longer explanation. " * 10})
    return messages


def _synthetic_stream_deltas(n: int = 500) -> list[str]:
    """Streamed token-ish chunks, interleaving visible prose with
    reasoning blocks, split at arbitrary boundaries (as a real streaming
    API would deliver them)."""
    chunks: list[str] = []
    pattern = (
        "Let me think about this. <think>Internal reasoning that should "
        "never reach the user, spanning several tokens of chain-of-thought "
        "content that a real model would produce.</think> Here is the "
        "visible answer for the user to read. "
    )
    text = pattern * (n // 20 + 1)
    step = max(1, len(text) // n)
    for i in range(0, len(text), step):
        chunks.append(text[i:i + step])
    return chunks


# ---------------------------------------------------------------------------
# Scenario: fast JSON serde (agent.serde) vs stdlib json
# ---------------------------------------------------------------------------

def bench_serde(report: Report, iterations: int) -> None:
    from agent.serde import fast_json as fj

    payload = {"messages": _synthetic_transcript(), "usage": {"input_tokens": 12345, "output_tokens": 678}}
    encoded_stdlib = json.dumps(payload).encode()

    def run_dumps():
        fj.dumps(payload)

    def run_loads():
        fj.loads(encoded_stdlib)

    def run_stdlib_dumps():
        json.dumps(payload).encode()

    def run_stdlib_loads():
        json.loads(encoded_stdlib)

    backend = "orjson" if fj.has_orjson() else ("msgspec" if fj.has_msgspec() else "stdlib (no fast backend installed)")
    report.add(Result("serde.dumps", f"current ({backend})", iterations, _timeit(run_dumps, iterations)))
    report.add(Result("serde.loads", f"current ({backend})", iterations, _timeit(run_loads, iterations)))
    report.add(Result("serde.dumps", "forced-fallback (stdlib json)", iterations, _timeit(run_stdlib_dumps, iterations)))
    report.add(Result("serde.loads", "forced-fallback (stdlib json)", iterations, _timeit(run_stdlib_loads, iterations)))


# ---------------------------------------------------------------------------
# Scenario: fast token estimator (agent.tokens) vs naive len // 4
# ---------------------------------------------------------------------------

def bench_tokens(report: Report, iterations: int) -> None:
    from agent.tokens import fast_estimator as fe

    text = ("The quick brown fox jumps over the lazy dog. " * 40)
    backend = "tiktoken" if fe.has_tiktoken() else "naive len//4 (tiktoken not installed)"

    def run_estimate():
        fe.estimate(text)

    def run_naive():
        fe.naive_estimate(text)

    report.add(Result("tokens.estimate", f"current ({backend})", iterations, _timeit(run_estimate, iterations)))
    report.add(Result("tokens.estimate", "forced-fallback (naive len//4)", iterations, _timeit(run_naive, iterations)))


# ---------------------------------------------------------------------------
# Scenario: TOON vs json.dumps -- both wall-clock AND token-count (issue
# #14/#16). Every other scenario here is a pure speed comparison; this one
# is dual-purpose because the point of TOON isn't encode/decode speed, it's
# how many tokens the *model* has to read. Real payload shapes actually
# used at LLM-prompt boundaries in this repo: a uniform array of objects
# (agent.context_engine's own docstring example), a tool-result dict
# (write_file's files_modified), and a small error payload
# (context_engine.handle_tool_call's default).
# ---------------------------------------------------------------------------

def bench_toon(report: Report, iterations: int) -> None:
    from agent.toon_codec import to_toon
    from agent.tokens.fast_estimator import estimate, has_tiktoken

    payloads = {
        "uniform_array_20_users": {
            "users": [
                {"id": i, "name": f"user{i}", "active": i % 2 == 0, "role": "member"}
                for i in range(20)
            ]
        },
        "tool_result_files_modified": {
            "success": True,
            "files_modified": [f"src/module_{i}.py" for i in range(15)],
        },
        "context_engine_error": {"error": "Unknown context engine tool: lcm_grep"},
    }
    tokenizer_label = "tiktoken cl100k_base (real BPE)" if has_tiktoken() else "naive len//4 (tiktoken not installed)"

    for name, payload in payloads.items():
        json_text = json.dumps(payload, ensure_ascii=False)
        toon_text = to_toon(payload)
        raw_tokens = estimate(json_text)
        compressed_tokens = estimate(toon_text)
        saved_pct = (
            round(100.0 * max(0, raw_tokens - compressed_tokens) / raw_tokens, 1)
            if raw_tokens else 0.0
        )

        def run_toon(_payload=payload):
            to_toon(_payload)

        def run_json(_payload=payload):
            json.dumps(_payload, ensure_ascii=False)

        report.add(Result(
            f"toon.encode[{name}]", f"current (TOON, {tokenizer_label})", iterations,
            _timeit(run_toon, iterations),
            notes=f"tokens: {raw_tokens} json -> {compressed_tokens} toon ({saved_pct}% saved)",
        ))
        report.add(Result(
            f"toon.encode[{name}]", f"forced-fallback (json.dumps, {tokenizer_label})", iterations,
            _timeit(run_json, iterations),
            notes=f"tokens: {raw_tokens} json (baseline, chars={len(json_text)})",
        ))


# ---------------------------------------------------------------------------
# Scenario: think-tag scrubbing throughput (no fallback branch exists;
# this is a regression baseline, not a before/after comparison)
# ---------------------------------------------------------------------------

def bench_think_scrubber(report: Report, iterations: int) -> None:
    from agent.think_scrubber import StreamingThinkScrubber

    deltas = _synthetic_stream_deltas()

    def run_once():
        scrubber = StreamingThinkScrubber()
        for d in deltas:
            scrubber.feed(d)
        scrubber.flush()

    # `iterations` full-stream replays would be excessive; scale down since
    # each "op" already processes hundreds of deltas.
    reps = max(1, iterations // 20)
    total = _timeit(run_once, reps)
    report.add(Result(
        "think_scrubber.feed (full stream)",
        "current (precomputed lowercase tag tuples)",
        reps,
        total,
        notes=f"{len(deltas)} deltas/stream, {reps} streams — no legacy baseline retained in-repo to compare against",
    ))


# ---------------------------------------------------------------------------
# Scenario: Anthropic prompt-cache marker injection — shallow-copy-of-4
# (current) vs full-transcript deepcopy (pre-0.19.0 baseline, reimplemented
# here from the same messages for a direct comparison)
# ---------------------------------------------------------------------------

def _legacy_apply_anthropic_cache_control(api_messages, cache_ttl="5m", native_anthropic=False):
    """Pre-0.19.0 baseline: deep-copy the ENTIRE transcript on every call,
    then apply the same markers via the current (shared) marker logic."""
    from agent.prompt_caching import _apply_cache_marker, _build_marker

    if not api_messages:
        return list(api_messages)
    messages = copy.deepcopy(api_messages)
    marker = _build_marker(cache_ttl)
    system_indices = [i for i, m in enumerate(messages) if m.get("role") == "system"]
    non_system_indices = [i for i, m in enumerate(messages) if m.get("role") != "system"]
    for i in system_indices:
        _apply_cache_marker(messages[i], marker, native_anthropic=native_anthropic)
    for i in non_system_indices[-3:]:
        _apply_cache_marker(messages[i], marker, native_anthropic=native_anthropic)
    return messages


def bench_prompt_caching(report: Report, iterations: int) -> None:
    from agent.prompt_caching import apply_anthropic_cache_control

    messages = _synthetic_transcript(n_messages=40)  # long-ish session

    def run_current():
        apply_anthropic_cache_control(messages)

    def run_legacy():
        _legacy_apply_anthropic_cache_control(messages)

    reps = max(1, iterations // 5)  # each op copies a 40-message transcript
    report.add(Result("prompt_caching.apply_anthropic_cache_control", "current (shallow list + deepcopy ≤4 marked msgs)", reps, _timeit(run_current, reps)))
    report.add(Result("prompt_caching.apply_anthropic_cache_control", "legacy baseline (deepcopy entire transcript)", reps, _timeit(run_legacy, reps)))


# ---------------------------------------------------------------------------
# Scenario: deterministic router latency (agent.router)
# ---------------------------------------------------------------------------

def bench_router(report: Report, iterations: int) -> None:
    from agent.router import default_router

    router = default_router()
    trivial_inputs = ["help", "ping", "what time is it?", "pwd", "echo hello world"]

    def run_route():
        for text in trivial_inputs:
            router.route(text)

    total = _timeit(run_route, iterations)
    report.add(Result(
        "router.route (trivial inputs)",
        "current (regex no-LLM router)",
        iterations * len(trivial_inputs),
        total,
        notes="each match avoids an LLM round-trip entirely (network + inference latency, not measured here)",
    ))


# ---------------------------------------------------------------------------
# Scenario: dependent tool-call chain — serial vs DAG (issue #115)
# ---------------------------------------------------------------------------

def bench_dag_vs_serial(report: Report, iterations: int) -> None:
    """Synthetic 3-stage x N-call dependency chain: stage 2 depends on
    stage 1's output, stage 3 depends on stage 2's — the exact "dependent
    tool-chain" shape issue #115 targets. Compares wall-clock of running
    it fully serially (today's assumption for any batch with cross-call
    dependencies) against agent.tool_executor.run_dag_tool_batch's
    level-parallel DAG scheduling. Uses a small artificial per-call delay
    (a real tool call has real I/O latency; a truly instant no-op call
    would make level-parallelism's benefit vanish under measurement
    noise) — this isolates the SCHEDULING win, not raw call overhead.
    """
    import asyncio

    from agent.async_dag import DagNode
    from agent.tool_executor import run_dag_tool_batch

    N = max(1, iterations // 200)  # keep total scenario time reasonable
    PER_CALL_DELAY_S = 0.01

    class _FakeAgent:
        def _invoke_tool(self, function_name, function_args, effective_task_id, *_, **__):
            time.sleep(PER_CALL_DELAY_S)
            return {"tool": function_name, "args": function_args}

    def _build_nodes():
        nodes = []
        for i in range(N):
            s1, s2, s3 = f"s1-{i}", f"s2-{i}", f"s3-{i}"
            nodes.append(DagNode(node_id=s1, tool="stage1", args={"i": i}))
            nodes.append(DagNode(node_id=s2, tool="stage2", args={"input": f"$ref:{s1}"}, depends_on=(s1,)))
            nodes.append(DagNode(node_id=s3, tool="stage3", args={"input": f"$ref:{s2}"}, depends_on=(s2,)))
        return nodes

    def _run_serial():
        agent = _FakeAgent()
        nodes = _build_nodes()
        outputs: dict = {}
        for node in nodes:
            from agent.async_dag.executor import _resolve_refs

            resolved = _resolve_refs(node.args, outputs)
            outputs[node.node_id] = agent._invoke_tool(node.tool, resolved, "bench")

    t0 = time.perf_counter()
    _run_serial()
    serial_total = time.perf_counter() - t0

    def _run_dag():
        agent = _FakeAgent()
        nodes = _build_nodes()
        asyncio.run(run_dag_tool_batch(agent, nodes, "bench", max_concurrency=N * 3))

    t0 = time.perf_counter()
    _run_dag()
    dag_total = time.perf_counter() - t0

    speedup = serial_total / dag_total if dag_total > 0 else float("inf")
    report.add(Result(
        "tool_executor.dag_vs_serial (3-stage chain)",
        f"serial (N={N} chains)",
        N * 3,
        serial_total,
        notes=f"speedup vs DAG: {speedup:.2f}x",
    ))
    report.add(Result(
        "tool_executor.dag_vs_serial (3-stage chain)",
        f"DAG level-parallel (N={N} chains)",
        N * 3,
        dag_total,
        notes=f"speedup vs serial: {speedup:.2f}x (AC target: >= 2x)",
    ))


# ---------------------------------------------------------------------------
# Scenario: message-history token estimator backends (issue #111)
# ---------------------------------------------------------------------------

def _synthetic_message_history(n: int, with_images: bool) -> list:
    """Build a representative OpenAI-style message history for the token
    estimator bench: alternating user/assistant text turns, with every 7th
    user turn carrying a base64-ish "image" content part when
    ``with_images`` is set (roughly one screenshot per compression-relevant
    burst of turns, not one per message)."""
    text_block = (
        "Let's look at the failing test output and figure out what changed. "
        "The traceback points at line 42 of the config loader. "
    ) * 6
    fake_b64 = "A" * 200_000  # ~1MB base64 stand-in, same order of magnitude the issue's docstring warns about
    messages = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        if with_images and role == "user" and i % 14 == 0:
            content = [
                {"type": "text", "text": text_block},
                {"type": "image", "image": fake_b64},
            ]
        else:
            content = text_block
        messages.append({"role": role, "content": content})
    return messages


def _message_shadow_strings(messages: list) -> tuple[list, int]:
    """Reproduce agent.model_metadata._estimate_message_chars/_count_image_tokens'
    exact text-vs-image split, but return the actual shadow strings (not just
    their lengths) so a token-estimator BACKEND swap can be benched fairly —
    every variant below counts tokens for the identical text, so only the
    chars-to-tokens step differs, and image-token semantics (flat 1500/image,
    see agent.model_metadata._count_image_tokens) are untouched by all three."""
    from agent.model_metadata import _count_image_tokens

    _IMAGE_TOKEN_COST = 1500
    shadows: list = []
    image_tokens = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            cleaned = []
            for part in content:
                if isinstance(part, dict) and part.get("type") in {"image", "image_url", "input_image"}:
                    cleaned.append({"type": part.get("type"), "image": "[stripped]"})
                else:
                    cleaned.append(part)
            shadow = {**msg, "content": cleaned}
        else:
            shadow = msg
        shadows.append(str(shadow))
        image_tokens += _count_image_tokens(msg, _IMAGE_TOKEN_COST)
    return shadows, image_tokens


def bench_message_tokens_backends(report: Report, iterations: int) -> None:
    """Issue #111: bench the message-history token estimator's text-to-token
    backend (current Python len//4 arithmetic vs tiktoken vs the Rust
    extension) across the exact history sizes and image/no-image split the
    issue's acceptance criteria name (20/200/1000 messages). Image-token
    accounting is identical across all three (see ``_message_shadow_strings``)
    -- only the chars-to-tokens step for plain text changes, so this isolates
    the backend decision without touching the image-cost contract.

    tiktoken is NOT a declared project dependency (checked: absent from
    pyproject.toml) -- when it isn't installed, that variant is reported as
    unavailable rather than skipped silently, so the gap is visible in every
    report instead of only in code comments.
    """
    import agent._hermes_fast as hf
    from agent.model_metadata import estimate_messages_tokens_rough

    try:
        import tiktoken  # type: ignore[import-not-found]
        _enc = tiktoken.get_encoding("cl100k_base")
    except ImportError:
        tiktoken = None
        _enc = None

    # Scale repetitions down for larger histories -- this scenario builds an
    # n-message history per rep, so the global --iterations default (2000)
    # would mean up to 2M message-dict builds for n=1000. 20/n keeps total
    # work roughly constant across sizes while still giving a stable median.
    for n in (20, 200, 1000):
        reps = max(3, min(iterations, 400 // max(1, n // 20)))
        for with_images in (False, True):
            messages = _synthetic_message_history(n, with_images)
            label = f"n={n}{'+img' if with_images else ''}"

            # Every variant rebuilds the shadow strings from `messages` INSIDE
            # its own timed closure -- production code estimates a fresh
            # history every turn, so a variant that gets pre-built shadows for
            # free would be an unfair (and wrong) comparison.
            def run_current():
                estimate_messages_tokens_rough(messages)

            report.add(Result(
                "tokens.message_history (#111)",
                f"current Python len//4 ({label})",
                reps,
                _timeit(run_current, reps),
            ))

            if hf.HAVE_RUST:
                def run_rust():
                    shadows, image_tokens = _message_shadow_strings(messages)
                    return sum(hf._rust.estimate_tokens_many(shadows)) + image_tokens  # type: ignore[attr-defined]

                report.add(Result(
                    "tokens.message_history (#111)",
                    f"rust_ext estimate_tokens_many ({label})",
                    reps,
                    _timeit(run_rust, reps),
                ))
            else:
                report.add(Result(
                    "tokens.message_history (#111)", f"rust_ext ({label})", 0, 0.0,
                    notes="rust_ext not built in this environment (maturin develop not run)",
                ))

            if _enc is not None:
                def run_tiktoken():
                    shadows, image_tokens = _message_shadow_strings(messages)
                    return sum(len(_enc.encode(s)) for s in shadows) + image_tokens

                report.add(Result(
                    "tokens.message_history (#111)",
                    f"tiktoken cl100k_base ({label})",
                    reps,
                    _timeit(run_tiktoken, reps),
                ))
            else:
                report.add(Result(
                    "tokens.message_history (#111)", f"tiktoken ({label})", 0, 0.0,
                    notes="tiktoken not installed -- not a declared project dependency (pyproject.toml has no tiktoken entry)",
                ))


# ---------------------------------------------------------------------------
# Scenario: warm daemon vs cold CLI start (issue #110 AC)
# ---------------------------------------------------------------------------

def bench_daemon_warm_start(report: Report, samples: int) -> None:
    """Warm-daemon speedup (issue #110 acceptance criterion): a real daemon
    ``start``/``status``/``stop`` round trip over its UNIX socket ("warm"),
    compared against the cold CLI-startup proxy ``bench_cli_startup`` also
    uses (subprocess cold-import of ``hermes_cli.main``, i.e. what a
    non-warmed invocation pays before it can even reach the daemon client).
    AC target: warm round trip is >= 30% faster than the cold-import proxy.

    Uses a short ``/tmp`` socket path (not ``REPO_ROOT``) for the same
    AF_UNIX path-length reason ``tests/hermes_cli/test_daemon.py`` documents.
    """
    if sys.platform == "win32":
        report.add(Result(
            "daemon.warm_vs_cold_start", "SKIPPED", 0, 0.0,
            notes="AF_UNIX sockets used by the daemon are not available on win32",
        ))
        return

    sock_path = f"/tmp/hermes_daemon_bench_{os.getpid()}_{int(time.time())}.sock"
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "hermes_cli.daemon", "start",
            "--warm-profile", "car", "--socket", sock_path,
        ],
        cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        deadline = time.time() + 15
        while time.time() < deadline and not os.path.exists(sock_path):
            time.sleep(0.1)
        if not os.path.exists(sock_path):
            report.add(Result(
                "daemon.warm_vs_cold_start", "FAILED", 0, 0.0,
                notes="daemon did not create its socket in time",
            ))
            return

        cold_times = []
        for _ in range(samples):
            t0 = time.perf_counter()
            r = subprocess.run(
                [sys.executable, "-c", "import hermes_cli.main"],
                cwd=str(REPO_ROOT), capture_output=True, timeout=60,
            )
            if r.returncode == 0:
                cold_times.append(time.perf_counter() - t0)

        warm_times = []
        for _ in range(samples):
            t0 = time.perf_counter()
            r = subprocess.run(
                [sys.executable, "-m", "hermes_cli.daemon", "status", "--socket", sock_path],
                cwd=str(REPO_ROOT), capture_output=True, timeout=15,
            )
            if r.returncode == 0:
                warm_times.append(time.perf_counter() - t0)

        if not cold_times or not warm_times:
            report.add(Result(
                "daemon.warm_vs_cold_start", "FAILED", 0, 0.0,
                notes="cold or warm subprocess samples failed to complete",
            ))
            return

        cold_median = statistics.median(cold_times)
        warm_median = statistics.median(warm_times)
        pct_faster = (1 - warm_median / cold_median) * 100 if cold_median > 0 else 0.0

        report.add(Result(
            "daemon.warm_vs_cold_start",
            f"cold (median of {len(cold_times)}, cold hermes_cli.main import)",
            1, cold_median,
            notes="proxy for a non-warmed invocation's full startup cost",
        ))
        report.add(Result(
            "daemon.warm_vs_cold_start",
            f"warm (median of {len(warm_times)}, `daemon status` round trip)",
            1, warm_median,
            notes=f"{pct_faster:.1f}% faster than cold (AC target: >= 30%)",
        ))
    finally:
        subprocess.run(
            [sys.executable, "-m", "hermes_cli.daemon", "stop", "--socket", sock_path],
            cwd=str(REPO_ROOT), capture_output=True, timeout=15,
        )
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        for path in (sock_path, sock_path.replace(".sock", ".pid")):
            try:
                os.unlink(path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Scenario: CLI cold-import time (proxy for startup cost)
# ---------------------------------------------------------------------------

def bench_cli_startup(report: Report, samples: int) -> None:
    times = []
    last_error = "(no stderr)"
    for _ in range(samples):
        start = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, "-c", "import hermes_cli.main"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            timeout=60,
        )
        elapsed = time.perf_counter() - start
        if proc.returncode == 0:
            times.append(elapsed)
        else:
            lines = proc.stderr.decode(errors="replace").strip().splitlines()
            last_error = lines[-1] if lines else "(no stderr)"
    if not times:
        report.add(Result(
            "cli.cold_import(hermes_cli.main)", "FAILED", 0, 0.0,
            notes=f"subprocess import failed — {last_error} (missing project deps in this env?)",
        ))
        return
    median = statistics.median(times)
    report.add(Result(
        "cli.cold_import(hermes_cli.main)",
        f"median of {len(times)} subprocess samples",
        1,
        median,
        notes=(
            "measures module import only, not the plugin-discovery fast path "
            "(hermes_cli/main.py:_plugin_cli_discovery_needed docstring documents "
            "~500-650ms saved per invocation for builtin subcommands, not re-derived here)"
        ),
    ))


SCENARIOS: dict[str, Callable[[Report, int], None]] = {
    "serde": bench_serde,
    "tokens": bench_tokens,
    "toon": bench_toon,
    "think_scrubber": bench_think_scrubber,
    "prompt_caching": bench_prompt_caching,
    "router": bench_router,
    "dag_vs_serial": bench_dag_vs_serial,
    "message_tokens_backends": bench_message_tokens_backends,
}


def print_table(report: Report) -> None:
    headers = ("scenario", "variant", "ops", "total_s", "per_op_us", "notes")
    widths = [34, 42, 8, 10, 12, 60]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*[h.upper() for h in headers]))
    print(fmt.format(*["-" * w for w in widths]))
    for r in report.results:
        print(fmt.format(
            r.scenario[:34],
            r.variant[:42],
            str(r.ops),
            f"{r.total_s:.4f}",
            f"{r.per_op_us:.2f}",
            r.notes[:60],
        ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--iterations", type=int, default=2000, help="base iteration count for in-process scenarios (default: 2000)")
    parser.add_argument("--startup-samples", type=int, default=3, help="subprocess samples for the CLI cold-import scenario (default: 3)")
    parser.add_argument("--skip", action="append", default=[], choices=list(SCENARIOS) + ["cli_startup", "daemon_warm_start"], help="scenario(s) to skip")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of a table")
    args = parser.parse_args()

    report = Report()
    for name, fn in SCENARIOS.items():
        if name in args.skip:
            continue
        fn(report, args.iterations)
    if "cli_startup" not in args.skip:
        bench_cli_startup(report, args.startup_samples)
    if "daemon_warm_start" not in args.skip:
        bench_daemon_warm_start(report, args.startup_samples)

    if args.json:
        print(json.dumps([
            {
                "scenario": r.scenario,
                "variant": r.variant,
                "ops": r.ops,
                "total_s": r.total_s,
                "per_op_us": r.per_op_us,
                "notes": r.notes,
            }
            for r in report.results
        ], indent=2))
    else:
        print_table(report)
        print()
        print("Notes:")
        print("- 'current' rows use whatever is installed in this environment right now.")
        print("- 'forced-fallback' rows monkeypatch nothing at the process level; they call the")
        print("  fallback function/path directly, so they're valid regardless of what's installed.")
        print("- See docs/performance.md for what each module trades off and how to enable it.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
