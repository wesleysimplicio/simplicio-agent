# macOS resource pressure — Simplicio stack (8 GB class)

Session evidence: 2026-07-08, M1 8 GB, load 56, swap ~1.2 GB used, memory free ~8%.

## Probe commands (run in parallel)
```bash
sysctl hw.memsize hw.ncpu
memory_pressure 2>/dev/null | tail -5
sysctl vm.swapusage
top -l 1 | egrep 'Load Avg|PhysMem|CPU usage'
ps aux -r | head -20
pgrep -lf 'llama-server|cargo build|rustc --crate-name simplicio|gateway run'
launchctl list | egrep 'simplicio|hermes|llama|runtime.watch'
```

## Interpretation
| Signal | Bad | Likely cause |
|--------|-----|----------------|
| Load ≫ ncpu | load 40+ on 8 cores | CPU queue: rustc LTO, Spotlight, compiles |
| Swap used > 500 MB | swapins 100k+ | RAM full → everything feels slow |
| `rustc --crate-name simplicio` | high %CPU | `com.simplicio.runtime.watch` → release build |
| Two `llama-server` | :11435 + :8090 | Dual models on 8 GB |
| Gemma `-c 65536` | in ProgramArguments | KV cache reservation — avoid on 8 GB |

## LaunchAgents (this host pattern)
| Label | Role |
|-------|------|
| `com.simplicio.local-llm` | Qwen on :11435 |
| `com.wesleysimplicio.llama-gemma4` | Gemma 4B on :8090 — heavy |
| `com.simplicio.runtime.watch` | Auto `cargo build --release` |
| `ai.hermes.gateway-simplicio-agent` | Simplicio Discord bot |
| `ai.hermes.gateway` | AlfradHD bot |

## Relief (external shell — not from inside gateway)
```bash
USER_UID=$(id -u)
launchctl bootout "gui/${USER_UID}/com.simplicio.runtime.watch"
launchctl bootout "gui/${USER_UID}/com.wesleysimplicio.llama-gemma4"  # if Qwen enough
pkill -f 'cargo build --release --locked' || true
simplicio runtime-profile use low
launchctl kickstart -k "gui/${USER_UID}/ai.hermes.gateway-simplicio-agent"  # after fast-stack rebuild
```

## Gateway restart pitfall
`simplicio-agent gateway restart` and `launchctl kickstart` from **inside** the Discord gateway session are blocked (SIGTERM to children). Use separate shell, subagent, or `~/.simplicio_agent/scripts/kickstart-simplicio-gateway.sh`.

## Discord latency note
If `config.yaml` uses remote provider (e.g. xAI Grok), turn latency includes API RTT. OS swap still slows tool execution locally — separate API wait from swap stall when reporting to user.