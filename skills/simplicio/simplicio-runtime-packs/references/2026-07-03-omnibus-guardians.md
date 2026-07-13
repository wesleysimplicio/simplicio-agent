# Sessão 03/07/2026 — Omnicoder + Guardians + Build Fixes

## O que foi feito

### Omnicoder/FabricBus (8-byte agent)
- Crate `simplicio-fabric` integrado ao runtime (`src/omnibus.rs`)
- 10 nós registrados no barramento: runtime, memory, gate, levi, voice, vision, browser, agents, savings, update
- Rotas HBP configuradas entre nós
- Omnicoder instanciado como `Lazy<Mutex<Omnicoder>>` global

### Guardians CLI
- `simplicio guardians --json` — mostra Isa (memória), Helo (runtime), Levi (gaps)
- Isa reporta 45K+ itens indexados na memória neural
- Helo reporta 66 comandos, 35 capabilities, 196 skills
- Levi reporta armed + 5 fontes externas (GitHub, Reddit, Wikipedia, Google, YouTube)
- Schema: `simplicio.guardians/v1`

### Build Fixes (migração asolaria)
- `vector_memory.rs`: restaurado do git (deletado no refactoring asolaria)
- `wavespeed`: removido de 12 arquivos (módulo obsoleto)
- `user_profile`: já estava íntegro
- Erro E0308: `Mutex::new(omni)` fix (Lazy retornava Omnicoder, não Mutex<Omnicoder>)
- Erro E0062: fields duplicados no guardians_command.rs corrigidos
- OOM fix: binary 26MB + SQLite 114MB causava SIGKILL. Binário do PATH deve ser `rm -f + cp` para evitar corrupção de inode.

### Desktop
- Desktop Electron movido para simplicio-agent/desktop/
- Original (Vite + React + TS + Electron) restaurado do archive/
- Runtime tem 12 módulos desktop (schemas/bridge)

### Levi Search Script
- `scripts/levi-search.sh` — busca em GitHub, Wikipedia
- Registra proveniência (fonte original)
- Chamado quando Isa + Helo não sabem responder
