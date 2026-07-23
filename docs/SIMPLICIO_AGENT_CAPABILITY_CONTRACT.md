# Simplicio Agent — Capability Contract

> Contrato canônico para Hermes/Simplicio agents. Ler antes de executar qualquer tarefa.

## Regra de absorção total
- Conhecer e usar o Runtime, banco neural, fast stack Rust, Tokio, catálogo de comandos e inventário de skills.
- Consultar o índice abaixo e carregar o SKILL.md completo apenas quando a tarefa acionar aquela skill.

## Fluxo obrigatório
1. Orientar: `simplicio runtime map --repo <repo> --for-llm markdown`.
2. Memória: `simplicio memory <query>`; contexto amplo: `simplicio memory all`.
3. Executar via CLI Simplicio; MCP é fallback.
4. Editar: `simplicio edit --plan <plan.json>`.
5. Validar com `simplicio validate` e testes reais.
6. Evidenciar com receipts; claims `MEASURED|` ou `UNVERIFIED|`.

## Potência operacional
- Runtime: schema registry, action gate, edit, validate, evidence, memória e fan-out.
- Tokio: paralelismo assíncrono; serializar apenas operações no mesmo arquivo/contrato.
- Fast stack: HAVE_RUST, orjson, msgspec, uvloop, tiktoken e h2; verificar sempre.
- Banco neural: SQLite + FTS5 + vector quando disponível; seeds + migrations.
- Economia: cache, mapas compactos, edição determinística, modelo local antes de remoto.
- Qualidade: funciona, não só compila; não declarar conclusão sem evidência.

## Comandos canônicos
```text
simplicio doctor --json
simplicio runtime map --repo <repo> --for-llm markdown
simplicio memory <query>
simplicio edit --plan <plan.json> --repo <repo>
simplicio validate "<task>" --repo <repo>
simplicio run "<task>" --repo <repo>
simplicio contracts smoke --json
simplicio evidence show --run-id <id>
simplicio agents delegate "<goal>"
simplicio shell -- <command>
```

## Skills
Índice gerado de **157 skills** em `~/.simplicio_agent/skills/`. O índice é persistido na memória neural; o procedimento completo permanece no SKILL.md.

| Skill | Descrição | Caminho |
|---|---|---|
| `apple` | Manage Apple Notes via memo CLI: create, search, edit. | `.simplicio_agent/skills/apple/apple-notes/SKILL.md` |
| `apple` | Apple Reminders via remindctl: add, list, complete. | `.simplicio_agent/skills/apple/apple-reminders/SKILL.md` |
| `apple` | Track Apple devices/AirTags via FindMy.app on macOS. | `.simplicio_agent/skills/apple/findmy/SKILL.md` |
| `apple` | Send and receive iMessages/SMS via the imsg CLI on macOS. | `.simplicio_agent/skills/apple/imessage/SKILL.md` |
| `asolaria-act-halting` | Adaptive Computation Time — decide quando parar de iterar com base em confiança + evidência real. Economiza tokens sem fabricar saída. | `.simplicio_agent/skills/asolaria-act-halting/SKILL.md` |
| `asolaria-agent-table` | Agent definition table — agents como dados. Describe roles, prerequisites, toolsets, evidence, and deliverables in one table. | `.simplicio_agent/skills/asolaria-agent-table/SKILL.md` |
| `asolaria-consolidation` | Karpathy-style consolidation: compila observações brutas em páginas markdown no fim da sessão e registra lessons duráveis. | `.simplicio_agent/skills/asolaria-consolidation/SKILL.md` |
| `asolaria-patterns` | Port dos padrões Asolaria (JesseBrown1980) para o Simplicio Runtime como primitivas determinísticas testáveis — N-Nest cosign/corrective gate, HRM two-level planner, BEHCS-256 supervisor federado. | `.simplicio_agent/skills/asolaria-patterns/SKILL.md` |
| `asolaria` | Monitorar diariamente os repositorios de JesseBrown1980/Asolaria, extrair conceitos, e integrar melhorias no ecossistema Simplicio. | `.simplicio_agent/skills/asolaria/asolaria-ecosystem-monitor/SKILL.md` |
| `autonomous-ai-agents` | Delegate coding to Claude Code CLI (features, PRs). | `.simplicio_agent/skills/autonomous-ai-agents/claude-code/SKILL.md` |
| `autonomous-ai-agents` | Delegate coding to OpenAI Codex CLI (features, PRs). | `.simplicio_agent/skills/autonomous-ai-agents/codex/SKILL.md` |
| `autonomous-ai-agents` | Configure, extend, or contribute to Hermes Agent. | `.simplicio_agent/skills/autonomous-ai-agents/hermes-agent/SKILL.md` |
| `autonomous-ai-agents` | Workflow e integração MCP+CLI do Simplicio como camada de execução do Hermes: Hermes = cérebro, Simplicio = mãos. | `.simplicio_agent/skills/autonomous-ai-agents/hermes-simplicio-hybrid/SKILL.md` |
| `autonomous-ai-agents` | Delegate coding to OpenCode CLI (features, PR review). | `.simplicio_agent/skills/autonomous-ai-agents/opencode/SKILL.md` |
| `autonomous-ai-agents` | Use when you want to cut agent input-token cost by rendering bulky context as dense PNG pages via pxpipe, especially for Claude Fable 5 or GPT 5.6, while keeping exact-string risk out of the image path. | `.simplicio_agent/skills/autonomous-ai-agents/pxpipe/SKILL.md` |
| `browser-harness` | Direct browser control via CDP. Use when the user wants to automate, scrape, test, or interact with web pages. Connects to the user's already-running Chrome. | `.simplicio_agent/skills/browser-harness/SKILL.md` |
| `browser-harness` | Create and configure Discord servers, categories, channels, and messages via Playwright browser automation. Covers login flow, DOM interaction patterns specific to Discord's React UI, and known pitfalls. | `.simplicio_agent/skills/browser-harness/discord-server-setup/SKILL.md` |
| `close-autopilot-issues` | Close Autopilot v5 issues and create new feature issues | `.simplicio_agent/skills/close-autopilot-issues/SKILL.md` |
| `code-review` | Comprehensive security and correctness audit of a branch's changes. Use for thermo nuclear, thermonuclear, or deep review requests, or branch/PR diff audits focused on bugs, breaking changes, security issues, devex regressions, and feature- | `.simplicio_agent/skills/code-review/thermo-nuclear-review/SKILL.md` |
| `code-review` | Launch both thermo-nuclear review subagents in parallel, then synthesize their findings. Use for thermos, double thermo review, or combined bug/security and code-quality branch audits. | `.simplicio_agent/skills/code-review/thermos/SKILL.md` |
| `computer-use` | / | `.simplicio_agent/skills/computer-use/SKILL.md` |
| `continuous-swarm-supervisor` | Use when evolving a terminal/chat interface (TUI) into a continuous, proactive, multi-agent swarm with Hermes-like capabilities. Covers persistent looping, agents delegate, rich tool calling, vector memory, proactivity, provider/model selec | `.simplicio_agent/skills/continuous-swarm-supervisor/SKILL.md` |
| `creative` | Dark-themed SVG architecture/cloud/infra diagrams as HTML. | `.simplicio_agent/skills/creative/architecture-diagram/SKILL.md` |
| `creative` | ASCII art: pyfiglet, cowsay, boxes, image-to-ascii. | `.simplicio_agent/skills/creative/ascii-art/SKILL.md` |
| `creative` | ASCII video: convert video/audio to colored ASCII MP4/GIF. | `.simplicio_agent/skills/creative/ascii-video/SKILL.md` |
| `creative` | Infographics: 21 layouts x 21 styles (信息图, 可视化). | `.simplicio_agent/skills/creative/baoyu-infographic/SKILL.md` |
| `creative` | Design one-off HTML artifacts (landing, deck, prototype). | `.simplicio_agent/skills/creative/claude-design/SKILL.md` |
| `creative` | Generate images, video, and audio with ComfyUI — install, launch, manage nodes/models, run workflows with parameter injection. Uses the official comfy-cli for lifecycle and direct REST/WebSocket API for execution. | `.simplicio_agent/skills/creative/comfyui/SKILL.md` |
| `creative` | Author/validate/export Google's DESIGN.md token spec files. | `.simplicio_agent/skills/creative/design-md/SKILL.md` |
| `creative` | Hand-drawn Excalidraw JSON diagrams (arch, flow, seq). | `.simplicio_agent/skills/creative/excalidraw/SKILL.md` |
| `creative` | Humanize text: strip AI-isms and add real voice. | `.simplicio_agent/skills/creative/humanizer/SKILL.md` |
| `creative` | Manim CE animations: 3Blue1Brown math/algo videos. | `.simplicio_agent/skills/creative/manim-video/SKILL.md` |
| `creative` | p5.js sketches: gen art, shaders, interactive, 3D. | `.simplicio_agent/skills/creative/p5js/SKILL.md` |
| `creative` | 54 real design systems (Stripe, Linear, Vercel) as HTML/CSS. | `.simplicio_agent/skills/creative/popular-web-designs/SKILL.md` |
| `creative` | Use when building creative browser demos with @chenglou/pretext — DOM-free text layout for ASCII art, typographic flow around obstacles, text-as-geometry games, kinetic typography, and text-powered generative art. Produces single-file HTML  | `.simplicio_agent/skills/creative/pretext/SKILL.md` |
| `creative` | Throwaway HTML mockups: 2-3 design variants to compare. | `.simplicio_agent/skills/creative/sketch/SKILL.md` |
| `creative` | Songwriting craft and Suno AI music prompts. | `.simplicio_agent/skills/creative/songwriting-and-ai-music/SKILL.md` |
| `creative` | Control a running TouchDesigner instance via twozero MCP — create operators, set parameters, wire connections, execute Python, build real-time visuals. 36 native tools. | `.simplicio_agent/skills/creative/touchdesigner-mcp/SKILL.md` |
| `data-science` | Iterative Python via live Jupyter kernel (hamelnb). | `.simplicio_agent/skills/data-science/jupyter-live-kernel/SKILL.md` |
| `devops` | Deploy a static (or PHP) site to an FTP host via `lftp mirror -R` and VERIFY the bytes landed correctly with an HTTP fetch + MD5 compare. Covers credential handling, runtime-dir excludes, and the mandatory post-deploy verification disciplin | `.simplicio_agent/skills/devops/ftp-site-deploy/SKILL.md` |
| `devops` | Build, deploy, and roll back the Simplicio Agent as an immutable versioned bundle (code + Python venv + Rust kernel together). Use when changing how the Simplicio Agent is deployed, migrating the live bot to a bundle, fixing deploy drift, o | `.simplicio_agent/skills/devops/simplicio-bundle-deploy/SKILL.md` |
| `dogfood` | Exploratory QA of web apps: find bugs, evidence, reports. | `.simplicio_agent/skills/dogfood/SKILL.md` |
| `email` | Himalaya CLI: IMAP/SMTP email from terminal. | `.simplicio_agent/skills/email/himalaya/SKILL.md` |
| `financas` | Banco do Brasil — API e serviços bancários BB | `.simplicio_agent/skills/financas/bb-br/SKILL.md` |
| `financas` | BTG Pactual — investimentos, contas e serviços BTG | `.simplicio_agent/skills/financas/btg-br/SKILL.md` |
| `financas` | Banco Inter — API e serviços digitais Inter | `.simplicio_agent/skills/financas/inter-br/SKILL.md` |
| `financas` | CLI para API Matera Edge Services — pagamentos, contas, transações, PIX e dados bancários no Brasil | `.simplicio_agent/skills/financas/matera-br/SKILL.md` |
| `financas` | Open Finance Brasil — conectividade bancária padronizada | `.simplicio_agent/skills/financas/open-finance-br/SKILL.md` |
| `financas` | PagBank — pagamentos, carteira e serviços PagSeguro | `.simplicio_agent/skills/financas/pagbank-br/SKILL.md` |
| `financas` | PicPay — carteira digital, pagamentos e serviços | `.simplicio_agent/skills/financas/picpay-br/SKILL.md` |
| `fix-enforcement` | Simplicio Hermes Plugin: enforcement mechanism, surviving tools, debugging techniques, and disable procedure. | `.simplicio_agent/skills/fix-enforcement/SKILL.md` |
| `gaming` | Host modded Minecraft servers (CurseForge, Modrinth). | `.simplicio_agent/skills/gaming/minecraft-modpack-server/SKILL.md` |
| `gaming` | Play Pokemon via headless emulator + RAM reads. | `.simplicio_agent/skills/gaming/pokemon-player/SKILL.md` |
| `github` | Inspect codebases w/ pygount: LOC, languages, ratios. | `.simplicio_agent/skills/github/codebase-inspection/SKILL.md` |
| `github` | Diagnose GitHub Actions failures systematically, especially startup failures that occur before any jobs start. | `.simplicio_agent/skills/github/github-actions-workflow-triage/SKILL.md` |
| `github` | GitHub auth setup: HTTPS tokens, SSH keys, gh CLI login. | `.simplicio_agent/skills/github/github-auth/SKILL.md` |
| `github` | Review PRs: diffs, inline comments via gh or REST. | `.simplicio_agent/skills/github/github-code-review/SKILL.md` |
| `github` | Create, triage, label, assign GitHub issues via gh or REST. | `.simplicio_agent/skills/github/github-issues/SKILL.md` |
| `github` | GitHub PR lifecycle: branch, commit, open, CI, merge. | `.simplicio_agent/skills/github/github-pr-workflow/SKILL.md` |
| `github` | Clone/create/fork repos; manage remotes, releases. | `.simplicio_agent/skills/github/github-repo-management/SKILL.md` |
| `github` | Submit fixes/PRs to NousResearch/hermes-agent in their accepted pattern. | `.simplicio_agent/skills/github/hermes-agent-contributing/SKILL.md` |
| `github` | Sync and verify multiple git repositories against their upstream branches, including worktree-aware branch alignment and push/readiness checks. | `.simplicio_agent/skills/github/multi-repo-git-sync/SKILL.md` |
| `github` | Systematic backlog triage for open-source contributions — find unassigned issues to work on, assess quick-fix viability, and manage workload across repos. | `.simplicio_agent/skills/github/oss-contribution-backlog/SKILL.md` |
| `github` | Drain ALL open GitHub issues across one or more repos with maximum parallelism — git worktree per issue, fan-out to delegate_task subagents, PR per issue, no issue closing, deferred compilation/tests until the end. Use when the user says re | `.simplicio_agent/skills/github/parallel-issue-drain/SKILL.md` |
| `higgsfield-generate` | / | `.simplicio_agent/skills/higgsfield-generate/SKILL.md` |
| `higgsfield-marketplace-cards` | / | `.simplicio_agent/skills/higgsfield-marketplace-cards/SKILL.md` |
| `higgsfield-product-photoshoot` | / | `.simplicio_agent/skills/higgsfield-product-photoshoot/SKILL.md` |
| `higgsfield-soul-id` | / | `.simplicio_agent/skills/higgsfield-soul-id/SKILL.md` |
| `mcp` | MCP client: connect servers, register tools (stdio/HTTP). | `.simplicio_agent/skills/mcp/native-mcp/SKILL.md` |
| `media` | Search/download GIFs from Tenor via curl + jq. | `.simplicio_agent/skills/media/gif-search/SKILL.md` |
| `media` | HeartMuLa: Suno-like song generation from lyrics + tags. | `.simplicio_agent/skills/media/heartmula/SKILL.md` |
| `media` | Audio spectrograms/features (mel, chroma, MFCC) via CLI. | `.simplicio_agent/skills/media/songsee/SKILL.md` |
| `media` | YouTube transcripts to summaries, threads, blogs. | `.simplicio_agent/skills/media/youtube-content/SKILL.md` |
| `mlops` | lm-eval-harness: benchmark LLMs (MMLU, GSM8K, etc.). | `.simplicio_agent/skills/mlops/evaluation/lm-evaluation-harness/SKILL.md` |
| `mlops` | W&B: log ML experiments, sweeps, model registry, dashboards. | `.simplicio_agent/skills/mlops/evaluation/weights-and-biases/SKILL.md` |
| `mlops` | HuggingFace hf CLI: search/download/upload models, datasets. | `.simplicio_agent/skills/mlops/huggingface-hub/SKILL.md` |
| `mlops` | llama.cpp local GGUF inference + HF Hub model discovery. | `.simplicio_agent/skills/mlops/inference/llama-cpp/SKILL.md` |
| `mlops` | vLLM: high-throughput LLM serving, OpenAI API, quantization. | `.simplicio_agent/skills/mlops/inference/vllm/SKILL.md` |
| `mlops` | AudioCraft: MusicGen text-to-music, AudioGen text-to-sound. | `.simplicio_agent/skills/mlops/models/audiocraft/SKILL.md` |
| `mlops` | SAM: zero-shot image segmentation via points, boxes, masks. | `.simplicio_agent/skills/mlops/models/segment-anything/SKILL.md` |
| `mobile` | Mobile apps integration for Simplicio — ngrok tunnel, QR pairing, push notifications via Expo, and remote device management via OpenCode mobile bridge. | `.simplicio_agent/skills/mobile/simplicio-mobile-apps/SKILL.md` |
| `note-taking` | Read, search, create, and edit notes in the Obsidian vault. | `.simplicio_agent/skills/note-taking/obsidian/SKILL.md` |
| `openclaw-imports` | Helps users discover and install agent skills when they ask questions like how do I do X, find a skill for X, is there a skill that can..., or express interest in extending capabilities. This skill should be used when the user is looking fo | `.simplicio_agent/skills/openclaw-imports/find-skills/SKILL.md` |
| `openclaw-imports` | / | `.simplicio_agent/skills/openclaw-imports/firecrawl/SKILL.md` |
| `openclaw-imports` | Use when building or reviewing web interfaces for quality, aesthetics, UX, accessibility, and guideline compliance. Unifies UI creation and UI audit into one class-level workflow. | `.simplicio_agent/skills/openclaw-imports/web-interface-design-workflow/SKILL.md` |
| `operations` | Use when the user needs executive-level guidance across strategy, cash, growth, prioritization, portfolio trade-offs, or near-term revenue pressure. Unifies CEO, CFO, and CMO lenses in one operating skill. | `.simplicio_agent/skills/operations/executive-operations-lenses/SKILL.md` |
| `operations` | Operate and troubleshoot local Hermes/Simplicio gateway services safely, including config edits, launchd/service restarts, and live verification with logs. | `.simplicio_agent/skills/operations/local-gateway-operations/SKILL.md` |
| `operations` | Recover from full-disk conditions (SIGKILL) on macOS and perform a clean reinstall of Simplicio Runtime from scratch — cloning, building, installing binaries, model download, Hermes plugin wiring. | `.simplicio_agent/skills/operations/macos-disk-recovery-and-simplicio-reinstall/SKILL.md` |
| `operations` | Use when monitoring or troubleshooting the personal portfolio observability stack (GH Actions, Paperclip, Discord bot, Hermes gateway, prod health). Covers the launchd-driven Portfolio Watch, alert routing to the SENTINEL Discord channel, a | `.simplicio_agent/skills/operations/portfolio-observability/SKILL.md` |
| `operations` | Full release flow for Simplicio — version bump, build, binary copy, version.txt, FTP deploy, and update manifest — plus runtime operations (Discord, launchd, .env, conventions). For the closed-source Rust CLI distributed as compiled binarie | `.simplicio_agent/skills/operations/simplicio-release-operations/SKILL.md` |
| `productivity` | Airtable REST API via curl. Records CRUD, filters, upserts. | `.simplicio_agent/skills/productivity/airtable/SKILL.md` |
| `productivity` | Gmail, Calendar, Drive, Docs, Sheets via gws CLI or Python. | `.simplicio_agent/skills/productivity/google-workspace/SKILL.md` |
| `productivity` | Geocode, POIs, routes, timezones via OpenStreetMap/OSRM. | `.simplicio_agent/skills/productivity/maps/SKILL.md` |
| `productivity` | Edit PDF text/typos/titles via nano-pdf CLI (NL prompts). | `.simplicio_agent/skills/productivity/nano-pdf/SKILL.md` |
| `productivity` | Notion API + ntn CLI: pages, databases, markdown, Workers. | `.simplicio_agent/skills/productivity/notion/SKILL.md` |
| `productivity` | Extract text from PDFs/scans (pymupdf, marker-pdf). | `.simplicio_agent/skills/productivity/ocr-and-documents/SKILL.md` |
| `productivity` | Install and select animated petdex mascots for Hermes. | `.simplicio_agent/skills/productivity/petdex/SKILL.md` |
| `productivity` | Create, read, edit .pptx decks, slides, notes, templates. | `.simplicio_agent/skills/productivity/powerpoint/SKILL.md` |
| `productivity` | Operate the Teams meeting summary pipeline via Hermes CLI — summarize meetings, inspect pipeline status, replay jobs, manage Microsoft Graph subscriptions. | `.simplicio_agent/skills/productivity/teams-meeting-pipeline/SKILL.md` |
| `provider-runtime-registry` | Implement a reusable registry for provider clients with TTL, explicit close, and testable reuse/isolation. | `.simplicio_agent/skills/provider-runtime-registry/SKILL.md` |
| `red-teaming` | Jailbreak LLMs: Parseltongue, GODMODE, ULTRAPLINIAN. | `.simplicio_agent/skills/red-teaming/godmode/SKILL.md` |
| `reporting` | Generate an evidence-backed single-file HTML report (real measured metrics + step-by-step) for any completed build/deliverable. Use when the user asks for a metrics report, build report, measure it, relatorio de passo a passo, or wants proo | `.simplicio_agent/skills/reporting/measured-build-report/SKILL.md` |
| `research` | Search arXiv papers by keyword, author, category, or ID. | `.simplicio_agent/skills/research/arxiv/SKILL.md` |
| `research` | Monitor blogs and RSS/Atom feeds via blogwatcher-cli tool. | `.simplicio_agent/skills/research/blogwatcher/SKILL.md` |
| `research` | Karpathy's LLM Wiki: build/query interlinked markdown KB. | `.simplicio_agent/skills/research/llm-wiki/SKILL.md` |
| `research` | Query Polymarket: markets, prices, orderbooks, history. | `.simplicio_agent/skills/research/polymarket/SKILL.md` |
| `research` | Write ML papers for NeurIPS/ICML/ICLR: design→submit. | `.simplicio_agent/skills/research/research-paper-writing/SKILL.md` |
| `savings-auto-record` | Configura auto-recording de token savings no Simplicio para qualquer LLM | `.simplicio_agent/skills/savings-auto-record/SKILL.md` |
| `scripts` | Ferramenta auxiliar para corrigir o enforcement plugin do Simplicio | `.simplicio_agent/skills/scripts/fix-enforcement-script/SKILL.md` |
| `simplicio-agent-max-performance` | Configuração máxima de paralelismo, delegação, orquestração e consciência viva (v2.2.0) | `.simplicio_agent/skills/simplicio-agent-max-performance/SKILL.md` |
| `simplicio-compress` | Cut output and memory tokens without losing meaning — terse prose levels (caveman-style) that preserve code/paths/URLs byte-for-byte, plus a one-time memory/doc compaction pass that pays back every future turn. Use when replies or worker re | `.simplicio_agent/skills/simplicio-compress/SKILL.md` |
| `simplicio-learn` | Persist what a run taught you so the next run is cheaper and more correct — mine high-signal lessons from the trajectory, dedup them, and write them back to AGENTS.md / memory so they're applied not re-derived. Use after a run or at session | `.simplicio_agent/skills/simplicio-learn/SKILL.md` |
| `simplicio-loop` | Cut output and memory tokens without losing meaning — terse prose levels (caveman-style) that preserve code/paths/URLs byte-for-byte, plus a one-time memory/doc compaction pass that pays back every future turn. Use when replies or worker re | `.simplicio_agent/skills/simplicio-loop/simplicio-compress/SKILL.md` |
| `simplicio-loop` | Persist what a run taught you so the next run is cheaper and more correct — mine high-signal lessons from the trajectory, dedup them, and write them back to AGENTS.md / memory so they're applied not re-derived. Use after a run or at session | `.simplicio_agent/skills/simplicio-loop/simplicio-learn/SKILL.md` |
| `simplicio-loop` | Iterate on a task autonomously until a typed completion-promise is genuinely true or a max-iteration cap is hit — the Ralph Wiggum loop, hardened. Use when the user says ralph loop, keep iterating until done, loop on this until it passes, o | `.simplicio_agent/skills/simplicio-loop/simplicio-loop/SKILL.md` |
| `simplicio-loop` | Terminal-first execution — answer facts with the shell, never with the LLM. Use whenever a step needs a fact about the filesystem, git, processes, or system resources, or runs a build/test/lint/diff whose output would flood context. Substit | `.simplicio_agent/skills/simplicio-loop/simplicio-orient/SKILL.md` |
| `simplicio-loop` | Deep, adversarial branch review — parallel subagents on separate rubrics (security/correctness, code-quality, and does-it-reproduce), spawned in one message, then deduped into one verdict. Runs for EVERY item, no TRIVIAL/SMALL shortcut — it | `.simplicio_agent/skills/simplicio-loop/simplicio-review/SKILL.md` |
| `simplicio-loop` | Autonomously complete a body of work (tasks, issues, cards, CI failures) on ANY LLM/runtime. Use when the user types /simplicio-tasks or asks to clear/finish/close/implement a queue of work — e.g. finish all open issues, close the bugs in m | `.simplicio_agent/skills/simplicio-loop/simplicio-tasks/SKILL.md` |
| `simplicio-meetily` | Integracao com Meetily — transcricao Parakeet 4x mais rapida que Whisper, diarizacao de falantes, sumarizacao Ollama | `.simplicio_agent/skills/simplicio-meetily/SKILL.md` |
| `simplicio-orient` | Terminal-first execution — answer facts with the shell, never with the LLM. Use whenever a step needs a fact about the filesystem, git, processes, or system resources, or runs a build/test/lint/diff whose output would flood context. Substit | `.simplicio_agent/skills/simplicio-orient/SKILL.md` |
| `simplicio-review` | Deep, adversarial branch review — parallel subagents on separate rubrics (security/correctness AND code-quality), spawned in one message, then deduped into one verdict. Use before merging non-trivial work, when the user says review this bra | `.simplicio_agent/skills/simplicio-review/SKILL.md` |
| `simplicio-runtime` | Simplicio Runtime file-write sandboxing — the MCP surface is sandboxed (#2674) but the CLI is not. When to use which, how to write files outside the repo, and the verify-before-claiming discipline for runtime internals. | `.simplicio_agent/skills/simplicio-runtime/simplicio-runtime-sandbox/SKILL.md` |
| `simplicio-tasks` | Autonomously complete a body of work (tasks, issues, cards, CI failures) on ANY LLM/runtime. Use when the user types /simplicio-tasks or asks to clear/finish/close/implement a queue of work — e.g. termine as issues abertas, feche os bugs do | `.simplicio_agent/skills/simplicio-tasks/SKILL.md` |
| `simplicio` | Port dos padrões Asolaria (JesseBrown1980) para o Simplicio Runtime — N-Nest-Prime, consolidator Karpathy, PID+watcher, BEHCS, tiered memory, observation pipeline | `.simplicio_agent/skills/simplicio/asolaria-patterns/SKILL.md` |
| `simplicio` | Padrão ouro para PRs aprovadas no Hermes Agent — validado contra PRs reais mergeadas. | `.simplicio_agent/skills/simplicio/hermes-pr-gold-standard/SKILL.md` |
| `simplicio` | Persist durable operator/project learnings — and absorb external/third-party repository knowledge — into the Simplicio neural database bootstrap and forward migrations, then validate, commit, and push safely. Covers the exact `simplicio edi | `.simplicio_agent/skills/simplicio/neural-memory-seeding/SKILL.md` |
| `simplicio` | Activate and verify the Simplicio Agent fast stack and macOS resource bottlenecks. Load for performance, slowness, PR #104, hermes_fast, or OS-level gargalo on 8GB Macs. PERFORMANCE not layout. | `.simplicio_agent/skills/simplicio/simplicio-agent-fast-stack/SKILL.md` |
| `simplicio` | Diagnóstico de topologia e verificação de ponta a ponta de que o repo `simplicio-agent` (main) está operante no gateway vivo cujo HERMES_HOME é `~/.simplicio_agent`. Inclui o pitfall mtime×checksum e o procedimento de sync skills repo→home. | `.simplicio_agent/skills/simplicio/simplicio-agent-main-reflection/SKILL.md` |
| `simplicio` | Cross-repo canonical-consumer / CLI rename + deprecation playbook for the Simplicio ecosystem (simplicio-mapper, simplicio-dev-cli, simplicio-loop, etc.). Use when a task rebrands, re-points, or renames a canonical agent/consumer/CLI across | `.simplicio_agent/skills/simplicio/simplicio-canonical-rename/SKILL.md` |
| `simplicio` | Keep Simplicio's local LLM always active on macOS, expose a stable local OpenAI-compatible endpoint, and wire the runtime to use it by default. Use for local-model startup, daemonization, endpoint verification, and recovery after llama.cpp/ | `.simplicio_agent/skills/simplicio/simplicio-local-llm-operations/SKILL.md` |
| `simplicio` | Add or evolve JSON-Schema contracts, fixtures, wheel/sdist packaging and clean-install validation for the simplicio-mapper repo (canonical observer/artifact envelopes like ContextSnapshot/ContextGraph). Trigger when touching contracts/*, si | `.simplicio_agent/skills/simplicio/simplicio-mapper-contracts/SKILL.md` |
| `simplicio` | Port Asolaria patterns into Simplicio Runtime as deterministic, testable primitives rather than LLM stubs. | `.simplicio_agent/skills/simplicio/simplicio-runtime-asolaria-porting/SKILL.md` |
| `simplicio` | Evolve the Simplicio Runtime by porting external patterns into runtime modules with deterministic edits, focused tests, and evidence. HARD MANDATE (Wesley 2026-07-08) — BOTH bots (AlfradHD ~/.hermes, Simplicio ~/.simplicio_agent) drive exec | `.simplicio_agent/skills/simplicio/simplicio-runtime-evolution/SKILL.md` |
| `simplicio` | Inventário completo, workflows validados, preferências do usuário e padrões operacionais do Simplicio Runtime v2.4.0 — 264 testes, 0 falhas | `.simplicio_agent/skills/simplicio/simplicio-runtime-packs/SKILL.md` |
| `simplicio` | Fluxo operacional padrão do Simplicio Agent para qualquer tarefa: orientar, lembrar, decidir, executar, validar, evidenciar e entregar em formato humano. | `.simplicio_agent/skills/simplicio/simplicio-standard-flow/SKILL.md` |
| `skill-b` | Some skill | `.simplicio_agent/skills/skill-b/SKILL.md` |
| `smart-home` | Control Philips Hue lights, scenes, rooms via OpenHue CLI. | `.simplicio_agent/skills/smart-home/openhue/SKILL.md` |
| `social-media` | Access Discord channels, messages, guilds, and users via REST API when browser tools are unavailable or blocked. Covers token retrieval, security workarounds, and common error codes. | `.simplicio_agent/skills/social-media/discord/SKILL.md` |
| `social-media` | X/Twitter via xurl CLI: post, search, DM, media, v2 API. | `.simplicio_agent/skills/social-media/xurl/SKILL.md` |
| `software-development` | Analyze external OSS repos via GitHub API (no clone), extract concepts, map to your own projects, and create structured integration issues with P0/P1/P2 priorities and success metrics. For cross-project planning work. | `.simplicio_agent/skills/software-development/external-repo-integration/SKILL.md` |
| `software-development` | Author in-repo SKILL.md: frontmatter, validator, structure, and writing-quality principles. | `.simplicio_agent/skills/software-development/hermes-agent-skill-authoring/SKILL.md` |
| `software-development` | Debug Node.js via --inspect + Chrome DevTools Protocol CLI. | `.simplicio_agent/skills/software-development/node-inspect-debugger/SKILL.md` |
| `software-development` | Plan mode: write an actionable markdown plan to .hermes/plans/, no execution. Bite-sized tasks, exact paths, complete code. | `.simplicio_agent/skills/software-development/plan/SKILL.md` |
| `software-development` | Debug Python: pdb REPL + debugpy remote (DAP). | `.simplicio_agent/skills/software-development/python-debugpy/SKILL.md` |
| `software-development` | Pre-commit review: security scan, quality gates, auto-fix. | `.simplicio_agent/skills/software-development/requesting-code-review/SKILL.md` |
| `software-development` | Parallel 3-agent cleanup of recent code changes. | `.simplicio_agent/skills/software-development/simplify-code/SKILL.md` |
| `software-development` | Throwaway experiments to validate an idea before build. | `.simplicio_agent/skills/software-development/spike/SKILL.md` |
| `software-development` | 4-phase root cause debugging: understand bugs before fixing. | `.simplicio_agent/skills/software-development/systematic-debugging/SKILL.md` |
| `software-development` | TDD: enforce RED-GREEN-REFACTOR, tests before code. | `.simplicio_agent/skills/software-development/test-driven-development/SKILL.md` |
| `thermo-nuclear-code-quality-review` | Run an extremely strict maintainability review for abstraction quality, giant files, and spaghetti-condition growth. Use for a thermo-nuclear code quality review, thermonuclear review, deep code quality audit, or especially harsh maintainab | `.simplicio_agent/skills/thermo-nuclear-code-quality-review/SKILL.md` |
| `workflow` | Class-level operating defaults for this user's Hermes/Simplicio setup — preferred fast-path service tier, approval bypass baseline, and how to keep the two separate. | `.simplicio_agent/skills/workflow/execution-defaults/SKILL.md` |
| `workflow` | Hybrid operating model: Hermes (brain) + Simplicio Runtime (body) + Asolaria gates. Rules of engagement when working with the Simplicio ecosystem. | `.simplicio_agent/skills/workflow/hermes-simplicio-hybrid/SKILL.md` |
| `workflow` | Decompose massive tasks into parallel independent workstreams dispatched via background subagents, with conflict-aware merging and final verification. | `.simplicio_agent/skills/workflow/large-task-decomposition/SKILL.md` |
| `workflow` | Audit many local git repos in parallel, consolidate implementation opportunities, and defer shipping work until the audit is complete. | `.simplicio_agent/skills/workflow/parallel-repo-audits/SKILL.md` |
| `workflow` | Execute tasks proactively without confirmation loops when user signals just finish it | `.simplicio_agent/skills/workflow/proactive-execution/SKILL.md` |
| `workflow` | Process GitHub issues autonomously via Simplicio's issue-factory pipeline: discover, worktree, sprint, validate, PR handoff. | `.simplicio_agent/skills/workflow/simplicio-issue-automation/SKILL.md` |
| `yuanbao` | Yuanbao (元宝) groups: @mention users, query info/members. | `.simplicio_agent/skills/yuanbao/SKILL.md` |

## Coordinator identity in public contracts and receipts

The versioned machine contract and receipt metadata identify the coordinator
without granting it global ownership. New payloads carry:

- `coordinator_kind`: coordinator implementation kind; Agent defaults to
  `simplicio-agent`.
- `coordinator_id`: the coordinator identity for the current contract path;
  Agent's stable default is `simplicio-agent`.
- `authority`: the bounded authority scope; Agent defaults to `session`.

These fields are additive to `machine-contracts/product/v1` and
`machine-contracts/receipt-metadata/v1`. Legacy machine contracts remain
upcastable and receive the safe Agent/session defaults. This local contract
slice does not prove Agent-to-Runtime interoperability or cross-repository
receipt propagation; those criteria remain `UNVERIFIED` until exercised with
the Runtime implementation.

## AgentHost boundary

- O Agent é um produto independente. O host publica um contrato neutro para
  qualquer consumidor e não importa nem depende do produto que o consome.
- O daemon atual anuncia `simplicio.agent-host/v1`, protocolo `agent/v1` e
  capabilities reais em toda resposta. `host.status` e `turn.start` continuam
  as superfícies de saúde e turno já existentes.
- Cada processo do daemon gera um `host_instance_id` opaco de 16–64 caracteres,
  estável apenas durante aquela execução e novo em um restart real. O campo é
  aditivo no envelope de discovery, em `host.status`, `host.advisories` e nos
  envelopes de `workspace.observe`/`workspace.advisory`. Clientes novos podem
  enviar o valor esperado nesses fluxos de replay; divergência falha fechado,
  para que resposta atrasada ou cursor de outra execução não seja confundido
  com o stream atual. Clientes v1 que omitem o campo continuam compatíveis,
  mas não recebem essa proteção até adotarem o rollout.
- `host.advisories` oferece apenas sinais operacionais de catálogo fixo
  (`ready`, backpressure, draining e resultado do turno), replay bounded e
  cursor monotônico. Não aceita prompt, segredo, conteúdo de workspace nem
  payload arbitrário.
- `workspace.observe` aceita somente um snapshot enviado explicitamente pelo
  cliente no schema `simplicio.workspace-observation/v1`: `workspace_id` opaco
  (1–64 caracteres, inicia alfanumérico e segue `[A-Za-z0-9._-]`), `revision`
  positiva e contígua e exatamente os
  metadados `changed_files`, `diagnostic_errors`, `diagnostic_warnings`
  (inteiros `0..100000`) e `test_status`
  (`unknown|not_run|passing|failing`). Campos extras, paths, nomes, texto,
  prompt, diff e segredo falham fechado; o Agent não lê o workspace.
- O producer determinístico publica somente códigos de catálogo fixo como
  `finding`, `risk` ou `suggestion` no schema
  `simplicio.workspace-advisory/v1`. Eventos carregam apenas facts allow-listed,
  `redaction=metadata_only` e `effect=none`; uma sugestão nunca executa Runtime,
  tool, provider/model ou outro efeito.
- `workspace.advisory` faz replay estritamente depois do cursor, isolado por
  `workspace_id`. O daemon retém no máximo 32 workspaces e 64 eventos por
  workspace; cursor futuro é erro e cursor anterior à janela retorna
  `truncated=true` com os eventos ainda retidos, sem salto silencioso.
- A recuperação do consumidor após restart é explícita: ao descobrir um novo host_instance_id válido, o cliente descarta cursor/incarnation anteriores, pede replay desde cursor=0 e ignora respostas atrasadas da geração antiga. O Agent não persiste nem zera cursores silenciosamente; mismatch continua fail-closed.
- Este slice é volátil e local: restart reinicia streams. Watcher/polling,
  leitura automática, persistência, liberação de workspace, approval/execução,
  UI e suporte IPC cross-platform continuam fora de escopo. O transporte atual
  permanece AF_UNIX; consumidores futuros não criam dependência inversa no
  Agent.

## Governança
- Não fabricar números, savings, testes ou resultados.
- Não fechar issue/PR sem mudança, teste/evidência e reconsulta.
- Preservar trabalho local; não resetar branches sujas.


## Complete command surface
Read `docs/SIMPLICIO_COMMAND_SURFACE.md` for the generated full command signatures. The live binary remains authoritative: run `simplicio --help` and the command-specific `--help` before execution.
