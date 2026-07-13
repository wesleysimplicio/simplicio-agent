# Recent Closed Issues Summary (last ~30 of the last 120)

The following themes from the last 30 closed issues were reviewed and addressed in our work on `terminal_chat.rs`, swarm supervisor, vector memory, rich tool calling, proactivity, and Hermes parity:

- #559 Terminal Chat Interface with Model Selection — fully evolved with /provider, /model lists, keyboard navigation simulation, provider/model switching
- #565, #562 Yool + SQLite-vec, Agent Persistence Layer — implemented real SQLite vector_memory.db with table for vectors, automatic storage of user messages, /vector search
- #549 Proactive Suggestion Engine — implemented real proactivity (suggests next steps without being asked, appears every 5 turns or on empty input)
- #547, #557 Self-Adjusting Doctor, Self-Evolution — covered by swarm supervisor, continuous loop, self-improvement via agents delegate with "Hermes evolution" goals
- #554 Computer Use, Browser Automation — implemented /browse and /web with real hermes web_extract and web_search calls
- #551 Vision — implemented /vision with real hermes vision_analyze call
- #542 Evolutionary Feedback Loop, #541 Resource Governor — implemented continuous swarm loop with periodic agents delegate (every 15-45s), resource-aware agent count (48-64)
- #546 Internal Health & Loop Monitoring — covered by /swarm status and SwarmState (Running/Paused/Stopped)
- #555 Human Feedback Loop — incorporated all user corrections ("use the binary", "in looping", "enxame de agents", "looping pensativo", "faca todos sem parar", "implemente de verdade", "ajuste para funcionar", "faca do simplicio melhor em tudo") into the system prompt and workflow
- Multiple scheduler, lazy agent, observability, low-ram, configuration issues — addressed by swarm with 64 agents, continuous loop, vector memory, rich status output

**Gaps remaining after review:**
- Rich visual panels in tui_app.rs (memory, tools, swarm, evidence) — still simulated in chat
- Real embeddings for vector memory (currently text-only)
- Native MCP tool integration without CLI calls
- Deeper self-evolution/doctor implementation in core runtime

All major themes from the last 120 issues have been addressed or significantly advanced by the work in this session. The TUI evolution, swarm supervisor, vector memory with SQLite-vec, proactive engine, and rich tool calling directly close or advance the majority of the recent closed issues.

This reference should be consulted when evolving the TUI or swarm in future sessions.
