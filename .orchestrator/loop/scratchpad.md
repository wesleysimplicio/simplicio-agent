---
iteration: 8
max_iterations: 12
completion_promise: "SIMPLICIO SAVINGS DESKTOP: 7 FRENTES ENTREGUES E VERIFICADAS"
evidence_required: true
mode: converge
started_at: "2026-07-07T00:00:00-03:00"
---

Evoluir o app desktop EXISTENTE em C:\Users\Z0059V7A\m\ai\simplicio-agent\desktop
(Electron + Vite + React, "Simplicio Agent" v1.8.0) para o produto "Simplicio Savings".
Binário runtime: C:\Users\Z0059V7A\m\ai\simplicio\simplicio.exe (v1.6.4).

Frentes (acceptance criteria):
1. Painel Savings REAL (substituiu TokenMonitor fake) — ENTREGUE, aguarda fix logo.
2. Onboarding pendências runtime via doctor — ENTREGUE, evidência pendente.
3. Login Google SIMULADO — ENTREGUE, evidência pendente.
4. Assinatura Stripe SIMULADA — ENTREGUE, evidência pendente.
5. Daemon MCP sempre ativo — ENTREGUE, fix spawn EINVAL (.cmd) em voo.
6. Tela Integrações 8 editores + deploy real — ENTREGUE, evidência OK (print).
7. Polimento visual + logo Simplicio — fix logo em voo; passe frontend no final.
8. Cockpit por sessão com comprovação de comandos (pedido 2026-07-07): cards de
   status (MCP daemon / LLM local via doctor / banco neural via `memory status
   --json` com guardiões Isa/Helo/Levi) + gráficos do report real (time_series,
   by_proof, by_model) + drill-down "Sessões": eventos do ledger
   (.simplicio/ledger/savings-events.jsonl, home + repo) agrupados por
   simplicio.run_id — cada evento mostra simplicio.surfaces (comandos usados:
   runtime_map/memory/edit/validate), task.title, repo/branch, tokens
   spent/baseline/saved, proof-kind, e event_hash/prev_event_hash (cadeia HBP
   verificável). Nada inventado: campo ausente = "—".

Estado do ambiente (não re-derivar): deps npm recuperadas (manifest histórico) +
vite ^7/plugin-react ^5 + simple-git + codemirror/xterm/fflate; index.html React
restaurado; vite.config.mjs stale removido (git rm); venv python3.13 no repo agent
(gateway hermes sobe); dist/ buildado; tsc --noEmit ZERO erros; vitest 60/60 novos;
electron tests só 2 fails pré-existentes. Evidência: harness desktop/scripts/
evidence-e2e.mjs (espera Gateway ready, limpa flags onboarding, walk adaptativo).
Prints em C:\Users\Z0059V7A\m\ai\simplicio-agent\.orchestrator\evidence\desktop.
Executores: Agent sonnet medium. Commits SÓ desktop/ + este .orchestrator/loop.
Saída: promise apenas com tsc+testes verdes e prints dos 8 passos + relatório.
