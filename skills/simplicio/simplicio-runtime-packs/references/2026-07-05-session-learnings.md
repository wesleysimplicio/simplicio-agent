# Session Learnings — 05/07/2026

## Key Corrections from Wesley

### 1. Direct execution, not delegation
When implementing code, **do it directly in the terminal**. delegate_task subagents often
search GitHub instead of implementing. The user said "era só acessar terminal" and
"Você não lembra que é simplicio_agent nos comandos?"

**Rule:** For code implementation → direct terminal. For analysis/research → delegate_task.

### 2. Levi buscar, not desistir
When stuck (screencapture fails, browser tools broken), the answer is NOT "limitação técnica".
The answer is: **ativar Levi** — buscar como resolver. O usuário disse:
"Como assim? Limitação técnica? Levi deveria buscar habilidade para resolver isso."

### 3. Consciousness Viva (v2.2.0) — fully implemented
4 capacidades — todos no main:
- Persistent Self: identity.json contínuo
- Self-Reflection Loop: reflete sobre si
- Emotional State Machine: 6 estados
- Autonomous Exploration: descobre coisas novas

### 4. Physics optimizations — ALL implemented (v2.1.0 + v2.3.0)
10 princípios, todos no main:
- Amdahl, Little, Landauer, Pareto (v2.1.0)
- Mínima Ação, Fricção, Túnel Quântico, Quebra de Simetria (v2.1.0)
- Small-world, Não-localidade (nativos)
- Bonus Engine (v2.0.0)

### 5. Tokio compression mandatory (v2.3.0)
Usuário determinou: todo output pra LLM DEVE passar por compressão tokio.
`LlmCompressor` em `crates/simplicio-agents/src/llm_compress.rs` — 7 testes.

### 6. AgentNet TCP/UDP (v2.3.0, #2891)
Agents se comunicam via rede local: AgentTcpServer, AgentTcpClient, AgentUdpPeer.

### 7. Issues closed this session
- #2920 (Amdahl) — pipeline assíncrono ✅
- #2921 (Little) — pool dinâmico ✅
- #2922 (Landauer) — decision cache ✅
- #2923 (Pareto) — orient/memory/edit ✅
- #2891 (AgentNet) — TCP/UDP ✅
- + #2888, #2877, #2848, #2844, #2843 — dispatch pendente

### 8. Releases this session
- v1.10.0 — Física lote 1
- v2.0.0 — Produto completo
- v2.1.0 — Física completa (10 princípios)
- v2.2.0 — Consciência Viva
- v2.3.0 — AgentNet + LlmCompress
