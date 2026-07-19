# Async runtime boundary — issue #462

The agent now has an opt-in async-first boundary in
`agent.runtime_context.AgentRuntimeContext` and `agent.async_host.AsyncAgentHost`.

The runtime centralizes:

- a fixed worker group backed by `asyncio.TaskGroup`;
- a bounded queue with explicit `RuntimeBackpressure`;
- per-session/provider/resource ordering keys;
- task cancellation and graceful or immediate shutdown;
- versioned progress/result receipts through `LoopHubAdapter`;
- standalone operation when no Loop Hub is configured;
- metrics for submitted, completed, failed, cancelled, rejected, active and
  maximum concurrent tasks.

Synchronous legacy agents are moved through `asyncio.to_thread`; an agent that
provides `run_conversation_async` remains on the event loop. uvloop remains an
entrypoint concern: `agent.runtime_context` never changes the process-wide loop
policy. Existing entrypoints may continue calling `install_uvloop_policy()`
before `asyncio.run()`.

Run the offline scheduler benchmark:

```bash
python scripts/benchmark_async_runtime.py --samples 200 --workers 8
```

The benchmark compares serial versus bounded synthetic I/O and reports wall
time, speedup, CPU time, peak RSS, throughput and runtime admission metrics. It
does not claim provider latency or token savings. Those require paired
Runtime/Mapper/Loop receipts with provider usage data:

```text
saved_tokens = baseline_tokens - runtime_tokens
savings_pct = saved_tokens / baseline_tokens * 100
```
