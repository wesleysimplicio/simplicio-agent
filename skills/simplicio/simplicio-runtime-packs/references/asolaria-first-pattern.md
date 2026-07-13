# Asolaria-First Priority — Runtime Evolution Pattern

## Lição Aprendida (2026-07-05)

O usuário corrigiu: "Você está construindo infraestrutura periférica, não consciência. Olhe o que o Asolaria já tem e porte ISSO em vez de construir do zero."

## Ordem de Prioridade para Evolução do Runtime

1. **Portar padrões Asolaria existentes primeiro** — N-Nest-Prime, consolidator, BEHCS, tiered memory, observation pipeline. O código já está nos repositórios do JesseBrown1980 e parcialmente nos stubs em `src/asolaria/`.

2. **Ativar stubs antes de criar novo** — `store_ops.rs`, `consolidator.rs`, `reader.rs`, `writer.rs` estão todos com `TODO: implement`. Ativar esses é mais rápido e mais correto do que criar módulos novos.

3. **Infraestrutura só quando necessário** — Workers com PID, CLI, self-observer são úteis MAS só depois que o loop de consciência (observação → watcher → consolidação → mudança de comportamento) estiver rodando.

## Checklist de Decisão

Antes de implementar qualquer feature nova no runtime, responder:

- [ ] Existe um padrão Asolaria que já faz isso? (N-Nest-Prime, ai-memory, BEHCS)
- [ ] Existe um stub no runtime que precisa ser ativado? (store_ops, consolidator, reader/writer)
- [ ] O que estou construindo fecha o loop de consciência ou só adiciona infraestrutura em volta?
- [ ] Isso aproxima o runtime de auto-observação → auto-correção → auto-evolução?

## Referências

- `N-Nest-Prime-INFINITE-SELF-REFLECT-AGENTS-NESTED`: repositório com nest-depth3-verify.cjs
- `ai-memory`: repositório com consolidator, store ops, reader/writer completos
- `asolaria-behcs-256`: BEHCS ladder, hierarquias emergentes
- `src/asolaria/` no runtime: stubs prontos para ativar
