---
name: simplicio-standard-flow
description: "Fluxo operacional padrão do Simplicio Agent para qualquer tarefa: orientar, lembrar, decidir, executar, validar, evidenciar e entregar em formato humano."
version: 1.0.0
author: Simplicio Agent
tags: [simplicio, workflow, standard, runtime, execution]
---

# Simplicio Standard Flow

Usar como protocolo base curto em toda tarefa, salvo quando a tarefa for puramente conversacional.

## Hierarquia correta
- `simplicio-tasks` é o orquestrador/loop completo para trabalho grande, filas, múltiplas etapas e execução autônoma prolongada.
- `simplicio-standard-flow` NÃO substitui `simplicio-tasks`.
- `simplicio-standard-flow` existe só como espinha curta e universal: orientar, lembrar, decidir, executar, validar, evidenciar e entregar humano.
- Quando a tarefa for grande ou iterativa, carregar e seguir `simplicio-tasks` primeiro.
- Para triagem em massa de issues com freeze de escopo, ver `references/issue-triage-scope-freeze.md`.
- Para contar backlog em todos os repositórios locais de `Projetos/ai` sem truncamento ou sobrecarga do host, ver `references/projects-ai-backlog-audit.md`. Use a Search API por repositório e separe upstreams de produto.

### Pitfall: TODA tarefa de desenvolvimento passa pelo loop — nunca bypass com delegate_task/execute_code

Correção viva (Wesley, 2026-07-11): "Utilize o simplicio-loop sempre para esses casos de tarefas de desenvolvimento." / "siga o simplicio-loop que garante a entrega real."

### Release waves correlacionadas: respeitar o DAG e distinguir implementação de prova

Quando mapper, dev-cli e loop mudam em conjunto, não tratar os PRs como um lote sem ordem. A sequência durável é:

1. mergear a implementação do mapper;
2. publicar a release do mapper;
3. atualizar o floor/dependência do dev-cli, validar, mergear e publicar a release do dev-cli;
4. atualizar o floor/dependência do loop, validar, mergear e publicar a release do loop;
5. executar a validação final ampla;
6. só então reconsultar issues e executar o close-gate.

- PR mergeado prova que código chegou à branch principal; não prova que a suíte completa está verde.
- Release publicada prova que o artefato/tag existe; não prova que checks hospedados ou testes amplos passaram.
- Se Actions estiver indisponível por billing, registrar `UNVERIFIED|` e não converter merge em “tudo validado”.
- Não afirmar que o `simplicio-loop` canônico foi executado só porque houve scratchpad, delegação ou uso do runtime. Para a claim forte, registrar evidência do ciclo `task → plan → execute → verify → watcher → close-gate`.
- Delegação paralela pode preparar PRs, mas merges/releases downstream ficam bloqueados até o predecessor do DAG estar publicado.
- Depois de fechar issues explicitamente autorizado pelo usuário, reconsultar ao vivo: `open issues = 0` e `open PRs = 0` por repositório. Registrar IDs/URLs e timestamps no journal.

Referência operacional: `references/correlated-release-wave.md`.

O `simplicio-loop` NÃO é só para trabalho "grande ou iterativo" — é o caminho OBRIGATÓRIO para QUALQUER tarefa de desenvolvimento com critério de aceite: mergear PR, fechar/corrigir issue, implementar feature, fechar um PR órfão. Contornar o loop com `delegate_task` ou `execute_code` gera **entrega parcial** (PR mergeado mas issue aberta, ou PR órfão nunca fechado).

- A regra "carregar simplicio-tasks primeiro quando a tarefa for grande/iterativa" vale, MAS o loop também cobre a tarefa de dev de item único: armar scratchpad, operar, validar no mesmo turno (evidence-gate), watcher-gate, e só então `<promise>`.
- O close-gate do loop (re-query ao vivo + evidência) é o que impede entrega parcial. Sem ele, o agente reporta "done" sem confirmar o estado real no GitHub.
- Ver `simplicio-loop` → `references/dev-task-loop-pattern.md` para o recipe concreto de merge de PR órfão dentro de uma iteração de loop.

## Regra central
- Hermes pensa.
- Simplicio executa.
- Tokio é o runtime padrão para concorrência, paralelismo, timers, filas, background work e I/O assíncrono no ecossistema Simplicio.
- Entrega ao usuário sempre em português limpo e formato humano, nunca dump cru de JSON.

### Mandato do usuário (Wesley, 2026-07-10): "Utilize sempre runtime cli nativo"
- O Simplicio Runtime CLI (`simplicio` / `simplicio-py`) é o CAMINHO PADRÃO de execução, não uma opção.
- **Diretriz de prioridade (Wesley, 2026-07-11): CLI direto é PRIMÁRIO, MCP é FALLBACK.** Use `simplicio <cmd>` no terminal primeiro; só caia para MCP (`mcp_simplicio_*`) quando o cliente já tem o server wired e a consulta é pontual. NÃO trate MCP como caminho primário.
- Em repositórios gerenciados (simplicio-runtime, simplicio-agent, Asolaria), NUNCA cair em ferramenta nativa do host (read_file/write_file/patch/grep) como primeira resposta.
- Se um comando do runtime "não funciona", PROBE o subcomando canônico e, se for ausente/quebrado, CORRIJA o runtime — não contorne.
- Exceção admitida: fallback pontual e verificado só após esgotar (1) probe do subcomando e (2) correção do runtime, registrado como gap a evoluir.
- Ver também: `references/runtime-cli-native-patterns.md`.

## Fluxo padrão

### Pitfall: comandos meta devem ser baratos
- `--help`, `-h`, `--version`, `-V`, `help` e `version` precisam sair por um caminho rápido antes de qualquer boot pesado.
- Nunca colocar descoberta de skills, onboarding, staged-update hooks, login de provider, chat/TUI ou qualquer inicialização cara antes desse retorno curto.
- Verificação mínima: os comandos meta devem completar mesmo quando o restante do runtime estiver indisponível ou custoso.
- Referência de sessão: `references/quick-meta-invocation-bootstrap.md`.


### 0. Classificar a tarefa
Separar em um destes modos:
1. conversa curta
2. inspeção/diagnóstico
3. edição/mutação
4. validação/verificação
5. execução longa/orquestração

Se houver ação real, usar Simplicio.

### 1. Orientar
Sempre começar por:
```bash
simplicio runtime map --repo <repo> --for-llm markdown
```

Objetivo:
- entender estrutura
- evitar leitura crua desnecessária
- reduzir tokens

### 2. Recuperar memória
Rodar:
```bash
simplicio memory "<consulta>"
```

Objetivo:
- recuperar decisões anteriores
- detectar padrões repetidos
- evitar retrabalho

### 3. Decidir a trilha
Escolher a menor trilha que resolve:

- só entender → `simplicio shell compact -- ...`
- alterar código → `simplicio edit --plan ...`
- validar tarefa → `simplicio validate "<task>" --repo <repo>`
- executar ponta a ponta → `simplicio run "<task>" --repo <repo>`

## Trilhas por tipo

### A. Inspeção
1. `runtime map`
2. `memory`
3. `shell compact`
4. resumo humano

#### When reviewing the latest change in a repo
Use this path when the user asks for "the latest update" or "what changed recently" in a subsystem:
1. orient first with `runtime map`;
2. identify the candidate commit(s) with `git log --grep` or `git log -n`;
3. inspect the commit summary with `git show --stat --name-only` before opening the full diff;
4. read the changed file(s) with line numbers around the touched blocks;
5. validate with a focused test that names the subsystem;
6. call out immediate follow-up gaps separately from the validated behavior.

Pointer: see `references/async-background-review.md` for a compact checklist and summary pattern.

#### Pitfall: `simplicio shell compact` e quoting excessivo
Quando usar `simplicio shell compact -- <cmd>` a forma mais estável é:
- colocar o diretório no `workdir` da tool/chamada hospedeira;
- passar o comando bruto depois de `--`;
- evitar embrulhar tudo em aspas extras com `cd ... && ...` se o `workdir` já resolve.

Heurística prática:
- preferir `workdir=<repo>` + `simplicio shell compact -- rg -n "..." .`
- evitar `simplicio shell compact -- 'cd <repo> && rg ... | head ...'` salvo quando o wrapper realmente precisar de shell composto
- evitar pipes e truncadores shell (`| head`, `| tail`) dentro do argumento quando o host já pode limitar/inspecionar o output por outros meios; primeiro tente o comando cru e deixe o `compact`/spill cuidar do volume
- se precisar muito de composição shell, tratar isso como exceção explícita; o caminho padrão é `workdir` + comando simples

Lição: se `shell compact` falhar com `No such file or directory` ou comportamento estranho de quoting, primeiro simplifique a invocação para `workdir` + comando bruto; não conclua imediatamente que o runtime não cobre a tarefa.

#### Pitfall: `simplicio shell compact` trunca o slice, mas o full output vive em `.simplicio/spill/`
Quando o comando tem volume grande ou usa pipe (`| head`, `| tail`), o `compact` devolve só um `slice` cortado e aponta para `.simplicio/spill/<timestamp>-<cmd>-<hash>.log`.
- Para inspecionar o diff/resultado completo, ler esse arquivo de spill com `read_file` (ou `simplicio file read`).
- Não conclua "vazio/0 mudanças" pelo slice do compact — o grep de `+`/`-` pode ser cortado. Sempre abra o spill quando o slice parecer incompleto.
- Ver também: `references/runtime-cli-native-patterns.md`.

### B. Edição
1. `runtime map`
2. `memory`
3. plano mecânico
4. `simplicio edit --plan ...`
5. assert local se cabível
6. validação
7. evidência
8. resumo humano

#### Quando o schema do `simplicio edit` não estiver fresco na memória
Não chute o JSON do plano. Dois caminhos, do mais rápido para o mais lento:

**Caminho A — leia o schema canônico (mais rápido, zero iteração).**
O contrato está em `schemas/edit-plan.schema.json` no repo `simplicio-runtime`. Formato mínimo que funciona (field `schema` é OPCIONAL):
```json
{
  "file": "scripts/install.sh",
  "operations": [
    { "op": "replace", "find": "<texto exato>", "with": "<substituição>" }
  ]
}
```
- `op` é obrigatório em cada operation; enum: `replace`, `replace_all`, `insert_before`, `insert_after`, `replace_line`, `insert_at_line`, `delete_line`, `append`, `prepend`, `create`.
- `replace`/`replace_all` usam `find`+`with`; `insert_*`/`append`/`prepend` usam `text`; `*_line` usam `line`.
- Copie o exemplo pronto em `references/edit-plan-schema-quickref.md`.

**Caminho B — probing guiado pelo erro (se não puder ler o schema).**
1. criar plano mínimo `operations: []` e rodar `simplicio edit --plan <arquivo> --repo <repo>`;
2. seguir cada erro (`file` ausente → `operations[].op` → `find`/`with`) até fechar.

**Pitfall crítico (causou 5 falhas numa sessão real):** `--plan` espera um **caminho de ARQUIVO**, nunca JSON inline. `simplicio edit --plan '{...}'` falha com `failed to read edit plan ...: No such file or directory`. Grave o plano em `/tmp/plan.json` (ou use `write_file`) e passe o path.

**Pitfall de invocação:** `simplicio edit --plan <arquivo> --json` (top-level) e `simplicio-py edit --repo <repo> --plan <arquivo.json> --apply --json` ambos aplicam. Em runtime recente `simplicio edit` roteia corretamente (não cai em `compat`); use o top-level como padrão e reserve `simplicio-py edit` para `--dry-run`/`--apply` explícitos.

Contrato confirmado: `file` no topo + `operations[]` com `op`+`find`+`with`. Isso evita cair em `patch` manual quando o caminho correto é `simplicio edit`.

Ver também: `references/edit-plan-probing.md`, `references/edit-plan-schema-quickref.md`.

#### Quando `simplicio edit --plan` falhar por encoding/Unicode em plano grande
Se o runtime rejeitar o plano com erro como `invalid edit plan JSON: invalid unicode codepoint in JSON string`, tratar isso como **gap do writer/CLI**, não como licença para abandonar o fluxo de validação.

Trilha correta:
1. manter `simplicio edit` como primeira tentativa;
2. se o plano grande quebrar no parser JSON, reduzir risco e cair para fallback **cirúrgico e verificado** (`patch` ou `write_file`) só para fechar a mudança imediata;
3. revalidar com testes focados + smoke do comando real;
4. registrar explicitamente que houve gap do runtime e que ele deve virar melhoria futura;
5. preferir reancorar por blocos exatos antes do fallback, em vez de reescrever o arquivo inteiro sem necessidade.

Não salvar a lição como 'simplicio edit não funciona'. A lição durável é: **falha de encoding em plano grande pede fallback mínimo verificado e posterior evolução do runtime**.

Ver também: `references/edit-plan-large-json-fallback.md`.

#### Quando o comando do runtime parece inexistente/quebrado — NÃO contorne com ferramenta nativa
Correção ao vivo (Wesley, 2026-07-09, escalada 3x): "Ta usando runtime?" → "Coloque hook forte pra usar runtime cli" → "Execução é com runtime, se ele não consegue, ajuste ele para conseguir". O agente estava usando `read_file`/`write_file`/`patch` nativos do Hermes em vez do runtime, e quando `simplicio read` devolveu um template de plano em vez do conteúdo, tratou como "runtime não cobre". Errado nos dois pontos.

Trilha correta quando um comando do runtime "não funciona":
1. **Não caia em ferramenta nativa** (read_file/write_file/patch/grep do host) como primeira resposta — viola a regra core e o hook forte já existente.
2. **Probe o subcomando canônico do próprio runtime.** Nesta sessão, `simplicio read` (top-level) caía no fallback de edit-plan e devolvia um template; o comando real era `simplicio file read --repo . <path>` (dispatch em `src/file_tools.rs`, registrado como `"file" | "files"` em `src/commands/mod.rs`). Sempre cheque o subcomando canônico antes de concluir ausência.
3. **Se for genuinamente ausente/quebrado, CORRIJA O RUNTIME** — não contorne. Fix desta sessão: adicionar `"read" => crate::file_tools::file_command(...)` no match top-level de `src/commands/mod.rs` via `simplicio edit --plan` (determinístico, 0 tokens pagos), compilar (`cargo build --release`) e testar, depois `git push origin main`.
4. Só após (2)+(3) esgotados é aceitável um fallback nativo pontual e verificado — e ainda assim registrado como gap do runtime a evoluir.

Lição durável: **gap de superfície do runtime = evolução do runtime (edit determinístico no dispatch), nunca workaround do agente.** O hook forte já está no lugar: `hooks/pre-commit` roda `simplicio deliver review`; `.claude/hooks/orient-gate.sh` bloqueia `Read|Grep|Glob` nativos e verbos crus `grep/rg/cat/find/sed/awk`; `git config core.hooksPath hooks` deve estar setado. O agente deve HONRAR o hook, não burlá-lo.

Ver também: `references/runtime-gap-fix-read-alias.md`.

#### Quando a mutação é pequena, localizada e já conhecida
Se você já sabe exatamente:
- o(s) arquivo(s) alvo,
- a troca textual exata,
- e consegue ancorar por hash,

prefira **ir direto para `simplicio edit --plan`** em vez de empurrar a mudança por `simplicio run`.

- `simplicio edit --plan <arquivo.json> --json` (top-level, roteia corretamente em runtime recente) e `simplicio-py edit --repo <repo> --plan <arquivo.json> --apply --json` ambos aplicam o plano. Prefira o top-level; use `simplicio-py edit --dry-run --json` para preview:
  ```bash
  simplicio edit --plan <arquivo.json> --json                       # aplica + resultado JSON
  simplicio-py edit --repo <repo> --plan <arquivo.json> --dry-run --json # preview sem aplicar
  ```
- Ver `references/runtime-cli-native-patterns.md`, `references/edit-plan-schema-quickref.md`.

Formato recomendado do plano:
- schema `simplicio.edit-plan/v1`
- `file` relativo ao `--repo`
- `expect_sha256` do arquivo antes da mudança
- `operations` mínima (`replace`, `replace_all`, `insert_*`, etc.)

Heurística:
- tarefa aberta/ambígua, múltiplos arquivos, descoberta ainda em curso → `run`
- correção cirúrgica com arquivo/hash/needle já conhecidos → `edit --plan`

### C. Validação
1. `runtime map`
2. `memory`
3. rodar `simplicio validate`
4. se falhar, isolar ponto quebrado
5. corrigir via `simplicio edit`
6. rerrodar validação
7. resumir PASS/FAIL em linguagem humana

#### Preferência explícita do usuário: testes em ondas
Quando o usuário disser para adiar os testes até o fim de uma wave/conjunto de issues, respeitar a ordem: não executar a suíte ampla nem declarar a issue concluída antes da wave final. Ainda assim:
- adicionar/atualizar os testes de aceitação junto com a implementação;
- executar apenas verificações não-executoras e baratas permitidas (diff check, formatter, análise estrutural), salvo instrução contrária;
- registrar no PR e na entrega `UNVERIFIED| testes adiados até a wave final`;
- manter PR e issue abertos; teste adiado nunca é evidência de merge/close-gate.

#### Revisão adversarial bloqueia entrega parcial
Para PRs medium/high, uma revisão que confirme qualquer AC não exercitado, escopo misturado, regressão de lógica ou falsa evidência produz `FIX-REQUIRED`/`BLOCK`, mesmo que o PR esteja `mergeable`. Corrigir a causa, atualizar o branch/PR e reconsultar metadata viva antes de qualquer merge ou close-gate. Não substituir uma revisão adversarial por `rustfmt`, `git diff --check` ou um PR aberto.

### D. Execução longa
1. `runtime map`
2. `memory`
3. planejar lote
4. executar por `simplicio run` ou `simplicio shell compact`
5. se demorar, background
6. validar
7. evidenciar
8. entregar só o que foi medido

#### Quando `mcp_simplicio_*` expirar em jobs agendados ou manutenção curta
Se uma consulta simples via MCP (`map`, `memory`, etc.) expirar em tarefa curta e local, não transformar isso em narrativa de indisponibilidade do runtime.

Trilha correta:
1. manter a ordem de prioridade: tentar MCP primeiro quando ele já cobre a operação;
2. se houver timeout, cair imediatamente para o comando CLI equivalente do Simplicio (`simplicio runtime map`, `simplicio memory`, etc.);
3. continuar a tarefa normalmente e reportar o fallback como evidência operacional, não como proibição futura;
4. registrar o aprendizado como padrão de resiliência: **MCP para caminho direto, CLI para continuidade quando o job precisa fechar agora**.

Heurística: em cron jobs, housekeeping e rotinas locais de baixa ambiguidade, timeout de MCP pede fallback rápido para CLI local — não abandono da execução.

### E. Build + Measure Report (HTML)
Quando o usuário pede um **deliverable + relatório estruturado** com métricas de tokens, tempo, ferramentas e raciocínio:

1. Construir o artefato principal (jogo, ferramenta, página).
2. **Antes de gerar o relatório**, medir o que puder: tamanho de arquivo, LOC, savings ledger, evidências.
3. Seguir o padrão em `references/html-task-report.md` para estruturar o relatório HTML:
   - Summary cards (stats)
   - Metadados (modelo, runtime, host)
   - Passo a passo tabelado
   - Decisões técnicas com justificativa
   - Token breakdown por ferramenta (com bar chart)
   - Custo estimado
   - Cadeia de evidências (MEASURED| / UNVERIFIED|)
   - Feature checklist
   - Gaps do runtime identificados
4. Abrir no navegador para verificar renderização.
5. Se não houver token tracker nativo, marcar como UNVERIFIED| e explicar a heurística.
6. Gravar no neural memory (`mcp_simplicio_neural` store) como referência futura.

Ver: `references/html-task-report.md` para a estrutura completa, constantes CSS, tags de badge e heurística de estimação de tokens.

## Atalhos de velocidade e economia

### Comandos de uso mais valioso no dia a dia
- orientar rápido: `simplicio runtime map --repo <repo> --for-llm markdown`
- lembrar antes de pensar: `simplicio memory "<query>"`
- ranking de capacidades: `simplicio capabilities rank "<task>" --json`
- conselho de próxima ação: `simplicio advise "<task>" --repo <repo> --json`
- shell com compressão: `simplicio shell compact -- <cmd>`
- edição zero-token: `simplicio edit --plan <plan.json>`
- loop focado de implementação: `simplicio dev-cli "<task>" --repo <repo>`
- execução ponta a ponta: `simplicio run "<task>" --repo <repo> --evidence`
- validação progressiva: `simplicio validate "<task>" --repo <repo>`
- prova e recibos: `simplicio evidence show --run-id <id>`
- economia medida: `simplicio savings report --repo <repo>`
- paralelismo seguro: `simplicio parallelism --repo <repo> --agents 600 --json`
- tecido Tokio: `simplicio tokio-runtime status --json`
- cache local: `simplicio cache status --json`

### Heurística curta
- primeira chamada: `runtime map`
- segunda chamada: `memory`
- se só precisa ver algo: `shell compact`
- se decidiu mudar: `edit`
- se precisa fechar loop: `validate` + `evidence`
- se tarefa for maior: `simplicio-tasks` no topo e `run/sprint/workflow` por baixo

### Quando a mudança é de comportamento do loop/runtime
- Se a mudança é sobre loop behavior, compliance, or runtime-level execution flow, prefira **atualizar a doc de runtime** em vez de reescrever a skill.
- Target canônico: `docs/simplicio-loop-compliance.md`.
- Se esse arquivo não existir ou estiver desatualizado, alinhe também `archive/website/docs/developer-guide/agent-loop.md` e `archive/website/docs/developer-guide/tools-runtime.md`.
- Reserve skill updates para regras de workflow duráveis, pitfall recorrentes, ou heurísticas de decisão que devam sobreviver a sessões futuras.
- See also: `simplicio-loop` → `references/loop-doc-targets.md`.

### Quando a tarefa é simplificar a superfície da CLI
Se o trabalho for reduzir comandos, juntar namespaces ou criar uma entrada única:
1. mapear aliases e grupos equivalentes já existentes antes de inventar novos comandos;
2. preferir um **front door semântico** (`work`, `repo`, `agent`) com lanes/subverbs internas em vez de só aumentar o `match` top-level;
3. fazer a canonicalização retornar o nome canônico real — não só documentar preferência sem aplicá-la;
4. manter compatibilidade por aliases top-level (`flow`, `workflow-task`, etc.) apontando para o front door novo;
5. testar o roteamento em três casos: subcomando explícito, alias equivalente e fallback padrão para a ação principal;
6. se a validação global ficar cara ou estourar timeout, usar testes focados por filtro de comando/roteamento e registrar isso separadamente da validação global.

Ver também: `references/cli-surface-consolidation.md`.

## Regra de saída
Nunca responder ao usuário com JSON cru.
Converter sempre para um destes formatos:
- status curto
- checklist
- tabela markdown
- diff resumido
- PASS/FAIL
- bloco de evidência `MEASURED|`

### Quando o usuário pede um resumo de integração/prioridades
- Começar pelos artefatos concretos do runtime e do loop (`runtime map`, arquivos de implementação, contratos de loop), não por memória isolada.
- Reduzir a síntese a no máximo três prioridades, cada uma ancorada em um arquivo ou superfície real.
- Para cada prioridade, explicitar em uma linha: o que já existe, o que falta, e por que isso é a próxima mudança do runtime.
- Preferir linguagem de integração: "wired but not integrated", "partial parity", "acceptance path not unified yet".
- Se houver um bloqueio de lookup/gating, continuar com evidência direta do repositório e mencionar o bloqueio de forma breve.
- Ver `references/runtime-evidence-synthesis.md` para o padrão de compressão usado nesta sessão.

### Regra de honestidade operacional
- Nunca escrever algo como `Operation interrupted.` ou equivalente a menos que essa frase tenha vindo de evidência real do runtime/comando.
- Se o trabalho estiver em andamento, dizer explicitamente o que já foi feito, o que está validado e o que ainda falta.
- Se o usuário perguntar `o que está fazendo?`, responder com estado operacional concreto: arquivo ou área em ajuste, teste rodado, resultado observado e próximo passo imediato.
- Erro de entrega da própria resposta deve ser assumido como erro do agente, não atribuído ao runtime.

### Quando um teste falha e você precisa saber se é seu
Se `cargo test --lib` (ou filtro) mostra 1 falha mas você só mexeu em módulos
aparentemente não-relacionados, NÃO assuma regressão sua. Confirmar com
`git stash`:
1. `git stash` (salva suas mudanças)
2. `cargo test --lib <filtro_do_teste>` → se AINDA falhar, é dívida pré-existente
3. `git stash pop` (restaura)

Na sessão 2026-07-09, `profiles::tests::test_create_and_switch` falhava mesmo
em árvore limpa (depende de estado de filesystem) — dívida do repo, não
introduzida pelas edições em `src/asolaria`/`src/hbp`. Não bloqueie o
land-on-main por falhas pré-existentes; separe "meus N verdes" de "1 falha
alheia" no relatório.

Esta regra vale IGUAL para `npm run lint` / `node --test` em repositórios Node
(simplicio-mapper etc.). Recipe concreto e reutilizável em
`simplicio-canonical-rename` → `references/stash-verify.md`:
1. `git stash push -m verify` (esconde TODAS as suas mudanças)
2. rode o gate exato (`npm run lint`, `node --test`)
3. se o vermelho for IDÊNTICO na árvore limpa → é pré-existente/ambiente, NÃO é sua edição
4. `git stash pop` e reconfirme que seus arquivos mudados ainda parseiam
5. NUNCA "corrija" um vermelho pré-existente editando arquivos fora do seu diff —
   isso polui o PR e mascara uma dívida real de ambiente/CI. Abra um ticket separado.

No simplicio-mapper há dois vermelhos conhecidos e estáveis (ambiente, não rebrand):
`video/scripts/generate-why-voiceover.mjs` (atributo `with {}` de import exige Node ≥18.20)
e `tests/unit/build-hamt-catalog.test.js` (`int.bit_count()` exige Python ≥3.10).
Ambos falham na árvore limpa; prove com stash e deixe o PR de rebrand limpo.

### Quando a tarefa é um rebrand / rename canônico cross-repo
Não reinvente o padrão — use `simplicio-canonical-rename` (skill irmã). Ela carrega:
- a matriz exata de arquivos a tocar (entry points, docs, generated, PRESERVE);
- o padrão de "alias depreciado mensurável" (STDERR once-per-process, stdout/JSON intactos);
- os invariantes do ecossistema (não reescrever `versioned_docs/`, não mexer em fixtures
  upstream Asolaria nem na atribuição YOOL de Victor "Dev Hermes" Genaro);
- o recipe de verificação via stash acima.

### Quando a validação global estoura timeout
Se `simplicio validate` não fecha dentro do timeout, não concluir falha genérica.
Use a trilha curta e mensurável:
1. isolar os módulos alterados;
2. rodar testes focados por arquivo ou área (`cargo test <filtro>`);
3. rodar ao menos a suíte `--lib` quando o problema for de código Rust interno;
4. se a superfície real estiver no binário CLI, validar também no target certo (`cargo test '<filtro>' --bin simplicio -- --nocapture`) em vez de assumir que `--lib` basta;
5. completar com um smoke do comando real (`cargo run --quiet -- <subcomando> ...`);
6. reportar claramente `validate timed out`, mas separar isso de `testes focados passaram/falharam`.

Lição operacional: timeout do validador não equivale automaticamente a regressão funcional, e filtro de teste no target errado também não prova integração real.

### Quando fechar uma mudança em repo git — NUNCA push direto a main, NUNCA force-push shared branch

O closure gate do loop (ver `docs/simplicio-loop-compliance.md` §6.1) exige PR para `main` com detalhes explícitos (o que mudou / como validado / evidência). Push direto a `main` NÃO satisfaz esse contrato — o usuário cobra o PR visível ("Cadê pr da implementação?").

Fluxo seguro obrigatório:
1. `git fetch origin` e trabalhar de `origin/main` atualizado.
2. `git checkout -b <tipo>/<curta>` (branch de feature, NUNCA commits soltos em main).
3. commitar (passa pelo `hooks/pre-commit` do Simplicio gate).
4. `git push -u origin <branch>`.
5. abrir PR: `simplicio shell compact -- gh pr create --base main --title "..." --body "<what/how/evidence>"`.
   - GAP DO RUNTIME: não existe `simplicio pr open` ainda — usar `gh` via `simplicio shell` é o caminho nativo aceito até o runtime ganhar o comando. Registrar esse gap como evolução futura.
6. merge após validação passar.

REGRA DE SEGURANÇA CRÍTICA (lição viva, sessão 2026-07-10):
- NUNCA `git push -f` (ou `git push` direto) em `main`/`origin/main` sem ANTES confirmar ancestry:
  `git fetch origin && git merge-base --is-ancestor origin/main <local-tip> && echo SAFE || echo DESTRUIRIA_TRABALHO_ALHEIO`
- O ref local `origin/main` fica OBSOLETO após pushes alheios; `git fetch --dry-run` NÃO atualiza o ref. Sempre `git fetch origin` real antes de any force op.
- Incidente real: ao tentar "desfazer" um push direto a main para abrir PR, um `git push -f <old-sha>:refs/heads/main` apagou o PR #3060 de outra pessoa (`75edb3e6`) do remote. O tip remoto real era `75edb3e6`, mas o ref local dizia `43e22397`/`2ea81cec`. Restaurado com `git push -f 75edb3e6:refs/heads/main` — mas o dano quase ocorreu. Raiz: não verifiquei se o remote main tinha commits que meu push direto havia suplantado.
- Se precisar mover o tip de uma branch compartilhada, prefira `git revert` + novo commit ou abrir PR; force-push só em branch pessoal/recém-criada e após ancestry check.

Ver `references/git-pr-closure-safety.md` para o roteiro completo e o transcript do incidente.

### Quando `cargo test <filtro>` diz `0 passed` e centenas de `filtered out`
Isso costuma significar **filtro no target errado**, não ausência de cobertura nem sucesso do caso novo.

Trilha correta:
1. não tratar `0 passed` como evidência útil por si só;
2. verificar se o filtro bate no binário, módulo ou harness certo antes de concluir qualquer coisa;
3. preferir `simplicio validate` como prova principal quando ele já cobre `targeted-unit-tests` e `build-lint-typecheck`;
4. usar `cargo test <filtro>` apenas como prova complementar, com target explícito e custo controlado;
5. se o teste focal recompilar o workspace inteiro e estourar timeout, reportar isso como limitação de trilha de teste direta — separado do status funcional já validado pelo runtime.

Heurística: `0 passed` + muitos `filtered out` = evidência de seleção ruim do teste, não de comportamento verificado.

## Formato final padrão

### Quando deu certo
- O que fiz
- O que mudou
- Como validei
- Estado atual
- Próximo gap do runtime

### Quando falhou
- O que tentei
- Onde falhou
- Evidência real do erro
- Próxima ação objetiva

## Evidência
Só afirmar o que foi medido.

Usar:
- `MEASURED|` para fatos comprovados
- `UNVERIFIED|` quando algo ainda não foi provado

## Anti-padrões
- não começar lendo arquivos crus se `runtime map` resolve
- não editar manualmente se `simplicio edit` resolve
- não entregar dump JSON ao usuário
- não afirmar sucesso sem validação
- não esconder falha de assert/teste
- não contornar comando do runtime com ferramenta nativa; se o comando quebrar, corrija o runtime (ver `references/runtime-gap-fix-read-alias.md`)

## Fechamento obrigatório
Ao fim de toda tarefa com ação real, registrar mentalmente:
1. o que o runtime já fez bem
2. qual gap ficou visível
3. qual melhoria futura deve virar evolução do runtime

Se a tarefa expôs um gap recorrente, transformar isso em melhoria do runtime ou skill atualizada.

#### Pitfall: separar build-churn de mudança pretendida antes do commit
- Comandos como `cargo build` / `npm install` sujam `Cargo.lock` / `package-lock.json` com entradas não-intencionais (ex.: `thiserror` adicionado ao lock).
- Antes de `git add .`, rode `git status --short` e `git diff --stat`; se houver lock/churn não relacionado, reverta com `git checkout -- <arquivo>` ou `git restore`.
- Commite SÓ os arquivos da mudança pretendida. O pre-commit gate do runtime valida, mas não filtra churn de lock.
- Ver `references/runtime-cli-native-patterns.md`.
