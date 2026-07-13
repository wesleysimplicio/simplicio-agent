# Consolidação de superfície de CLI

Sessão-base: unificação de comandos no `simplicio-runtime` em torno de um front door único `simplicio work`.

## Padrão reaproveitável

### Objetivo
Reduzir carga cognitiva da CLI sem quebrar compatibilidade:
- menos comandos top-level memoráveis;
- aliases preservados;
- roteamento explícito para uma intenção central.

### Receita
1. localizar grupos equivalentes já existentes (`EQUIVALENT_COMMAND_GROUPS`, aliases, help surface, erro `unknown <namespace> subcommand`);
2. escolher um front door semântico curto;
3. criar um classificador de lane/subverbo;
4. encaminhar subcomandos explícitos para handlers já existentes;
5. deixar entrada sem subcomando cair no caminho principal (geralmente `run`);
6. adicionar aliases top-level para transição suave;
7. validar com testes focados de roteamento.

## Exemplo concreto

Front door criado:
- `simplicio work`

Aliases equivalentes:
- `flow`
- `workflow-task`
- `workflow_task`

Lanes internas úteis:
- `plan`
- `decide`
- `resolve`
- `reason`
- `advise`
- `run` (default implícito)
- `validate`
- `evidence`
- `deliver`
- `resume`

## Casos mínimos de teste
- subcomando explícito: `work plan ...`
- alias top-level: `workflow-task plan ...`
- fallback default: `work "tarefa" ...` deve cair em `run`
- primeira flag: `work --json ...` não deve ser interpretado como subcomando textual
- preferência de alias: `SIMPLICIO_COMMAND_PREFERENCE` precisa alterar o canônico de verdade

## Lição de validação
Se `simplicio validate "<task>" --repo <repo>` ficar lento ou estourar timeout:
- não tratar timeout como regressão provada;
- rodar `cargo test --bin <bin> <filtro> -- --exact --nocapture` para os testes do roteador;
- validar ao menos o caminho funcional do binário (`./target/debug/<bin> <alias/subcomando> ...`).

## Sinais de que vale consolidar
- muitos aliases já existem mas continuam espalhados no `match` top-level;
- usuário precisa decorar namespace demais para a mesma intenção;
- há pares semânticos repetidos (`plan/run/validate/evidence`) espalhados por comandos diferentes;
- a canonicalização existente só normaliza no papel, mas não altera o fluxo real.
