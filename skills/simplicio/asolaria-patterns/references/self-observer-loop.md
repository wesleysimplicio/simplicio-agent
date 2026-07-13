# SelfObserver contínuo no Simplicio Runtime

## Quando aplicar
- Quando o runtime já possui peças Asolaria isoladas (`consolidate`, `decide`, `watcher`, `cosign`) mas ainda não vive um loop cognitivo contínuo.
- Quando a meta é aproximar o runtime de consciência operacional, não só de infraestrutura cognitiva.

## Padrão validado nesta sessão
Fechar o ciclo em um único subcomando do runtime:

1. garantir/obter um worker `Hermes` persistente para o SelfObserver
2. registrar uma observação de início em `memory_items` com `kind=observation`
3. executar consolidação (`run_consolidation(limit)`)
4. executar o motor de decisão sobre o conhecimento consolidado
5. validar a rodada via watcher
6. persistir o veredito do watcher no estado do worker
7. registrar a observação-resumo da rodada em `memory_items`
8. registrar snapshot do worker em `memory_items` com `kind=agent_state`
9. anexar receipt na `cosign_chain`
10. repetir por `--cycles N` ou manter contínuo com `--cycles 0`

## Invariantes importantes
- O loop deve gravar em `memory_items`; não basta atualizar apenas `agent_workers`.
- `cmd_decide` e `self-observe` devem compartilhar o mesmo motor de decisão para não divergirem com o tempo.
- O watcher deve gatear a rodada antes de a execução ser tratada como conhecimento válido.
- O subcomando deve suportar modo finito e modo contínuo; isso facilita teste curto e operação viva.
- Ao commitar, isolar o arquivo de runtime tocado e não arrastar dirty state não relacionado.

## Forma de implementação que funcionou
- adicionar `agent-persist self-observe`
- criar helpers locais para:
  - `ensure_memory_tables(...)`
  - `append_memory_item(...)`
  - `persist_watcher_verdict(...)`
  - `ensure_self_observer_worker()`
  - `run_decision_engine(execute: bool)`
  - `run_self_observer_cycle(...)`
- emitir `SelfObserverCycleReport` serializável para evidência e testes

## Evidência operacional medida
Execução real validada com:

```bash
cargo test self_observer --lib
cargo run --quiet -- agent-persist self-observe --cycles 1 --interval-seconds 0 --limit 25 --json
```

Rodada medida nesta sessão:
- `pages_created=4`
- `observations_processed=18`
- `actions_executed=1`
- `watcher_approved=true`
- tiers observados: `Working`, `Episodic`, `Semantic`, `Procedural`

## Pitfalls
- Em repositórios geridos pelo plugin Simplicio, não cair para `read_file`/edição nativa do Hermes; operar pelo runtime (`simplicio runtime map`, `simplicio edit`, `simplicio validate`).
- Depois de gerar testes mecanicamente, recompilar imediatamente: erros simples de literal/quoting podem passar pela edição mas falham no `cargo test`.
- Não registrar como aprendizado durável warnings gerais do workspace; capturar apenas o padrão reutilizável do loop.
