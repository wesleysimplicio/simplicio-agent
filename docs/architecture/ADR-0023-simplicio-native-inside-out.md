# ADR-0023: Transformação nativa inside-out do Simplicio Agent

- Status: proposed / future
- Date: 2026-07-13
- Decision owner: Simplicio
- Scope: `simplicio-agent` + bindings do `simplicio-runtime`

## Contexto

O produto nasceu de uma base upstream ampla e ainda preserva identidade, namespaces, variáveis, módulos, caminhos, protocolos e estruturas internas legadas. Trocar apenas superfícies públicas produziria um fork cosmeticamente diferente, mas estruturalmente dependente. Uma reescrita total, por outro lado, concentraria risco e impediria provar equivalência.

A direção do produto é um sistema operacional cognitivo compilado: execução determinística, contexto mínimo, latência quase instantânea, tokens remotos próximos de zero e escalada para um provedor frontier somente diante de incerteza real.

## Decisão

O Simplicio Agent será transformado **de dentro para fora**, em fatias pequenas, reversíveis e mensuráveis. O estado final não conterá referências à identidade upstream legada em nomes de variáveis, classes, módulos, pacotes, comandos, variáveis de ambiente, schemas, diretórios, mensagens, telemetria ou artefatos distribuídos. Compatibilidade temporária existirá somente em bridges isoladas, com prazo e critério de remoção.

A regra anterior de preservar nomes internos legados está revogada. Nenhuma nova referência legada pode ser introduzida fora do inventário temporário de migração.

## Arquitetura-alvo

```text
Evento
  -> fingerprint da intenção
  -> L0 receita/cache/precedente (zero modelo)
  -> L1 execução determinística (zero modelo)
  -> L2 interpretação local guiada (zero token pago)
  -> L3 provedor frontier com cápsula mínima
  -> EffectRequest tipado
  -> executor compilado
  -> validação + receipt HBP
  -> aprendizagem incremental
```

O modelo enxerga apenas cinco primitivas estáveis: `recall`, `inspect`, `decide`, `act` e `verify`. O capability broker resolve comandos e adapters internamente; schemas e skills são carregados sob demanda.

O hot path converge para crates nativos: kernel, router, context, memory, executor, scheduler, evidence, gateway, protocol e observer. Código Python permanece apenas em extensões frias durante a migração e sai do ciclo de resposta principal.

## Auto-modificação sem quebra

Toda mudança interna deve seguir esta transação:

1. **Inventariar** consumidores, estado, schemas e testes da fatia.
2. **Congelar o contrato observável** com fixtures e golden tests.
3. **Criar o caminho canônico novo** sem alterar o legado.
4. **Dual-read / shadow-run**: o caminho novo recebe a mesma entrada e sua saída é comparada sem produzir efeito duplicado.
5. **Canary por perfil/sessão** com feature flag fail-closed.
6. **Gate de equivalência** para comportamento, tokens, latência, memória e receipts.
7. **Promoção atômica** do novo caminho somente após gates verdes.
8. **Rollback automático** ao snapshot anterior se health-check ou live-commit divergir.
9. **Janela de observação** com telemetria sem dados sensíveis.
10. **Remoção do legado** apenas quando busca de consumidores, artefatos e rollback gate provarem ausência de dependentes.

Renomear e alterar comportamento na mesma fatia é proibido. Cada PR possui uma única fronteira, receipt e plano de reversão.

## Contrato source -> bot local

O checkout local e o processo ativo não podem divergir silenciosamente. O updater canônico deverá:

1. detectar instalação release, editable ou checkout Git;
2. adquirir lock e criar snapshot pre-update;
3. preservar mudanças locais em um patch/manifesto content-addressed;
4. executar fetch + fast-forward seguro ou stage de release assinado;
5. reaplicar mudanças locais compatíveis em staging, sem sobrescrever arquivos silenciosamente;
6. sincronizar dependências apenas quando lockfiles mudarem;
7. executar syntax/import/config/focused-smoke gates;
8. ativar atomicamente um ponteiro `current`;
9. solicitar restart ao supervisor por helper destacado, nunca pelo processo que será encerrado;
10. verificar que o gateway vivo reporta o commit/digest novo;
11. restaurar automaticamente o snapshot se startup, health ou commit attestation falhar;
12. emitir receipt contendo before/after, arquivos preservados, testes e rollback status.

Um `git pull` manual no checkout autoritativo deverá ser detectado pelo supervisor e tratado como update pendente; ele não vira produção até passar pelo mesmo stage/gate/activate. `simplicio-agent update` deverá capturar tanto atualizações remotas quanto alterações locais versionadas, sem perdê-las e sem declarar sucesso antes de o bot vivo provar o novo commit.

## Fases incrementais

1. **Constituição e inventário:** manifesto machine-readable de nomes legados, owners e expiry.
2. **Updater transacional:** source/release -> staging -> gates -> live commit -> rollback.
3. **Token governor:** roteamento L0-L3, orçamento por turno e métricas obrigatórias.
4. **Prompt microkernel:** cinco primitivas, lazy schemas e cápsulas content-addressed.
5. **Daemon nativo:** hot path Rust sempre quente; Python fora do caminho crítico.
6. **Controle físico:** decay do working set, entropia para escalada, PID de recursos e histerese de rotas.
7. **Gateway nativo:** plataformas e streaming conectados ao daemon; bridge legado isolado.
8. **Migração total de identidade:** namespaces, módulos, variáveis, env, paths, protocolos e artefatos.
9. **Eliminação do bridge:** scanner de source/package/runtime e clean install com zero referência não legalmente obrigatória.

## Metas de produto

- tarefas L0/L1: zero tokens remotos;
- pelo menos 80% das rotas rotineiras sem modelo remoto;
- prompt remoto típico menor que 2.000 tokens;
- schema fixo menor que 1 KiB;
- roteamento quente p50 menor que 10 ms;
- confirmação visual p95 menor que 100 ms;
- 100% das mutações com receipt e rollback;
- zero releitura de bytes de contexto inalterados;
- zero referências legadas no artefato final, exceto atribuição legal isolada quando obrigatória.

Metas são gates futuros, não resultados já alcançados. Cada issue deve anexar benchmark antes/depois.

## Consequências

A transformação demora mais que um replace-all, mas cada estágio continua instalável, atualizável e reversível. O bridge temporário aumenta complexidade durante a migração; em troca, reduz o blast radius e permite excluir o legado com evidência, não esperança.

## Critério de conclusão

Esta ADR termina somente quando o artefato instalado, o processo vivo, a configuração, os protocolos e o source scan satisfizerem os gates finais e o bridge temporário tiver sido removido. Documentação ou compilação isolada não constituem conclusão.

## GitHub execution map

The seven-issue P0 reconciliation is recorded in
[`native-p0-reconciliation.md`](native-p0-reconciliation.md) and its checked
manifest.  Each P0 issue has exactly one relation to the Native sequence; this
does not close or mutate any GitHub issue.  The local consistency gate is
`python scripts/check_program_graph.py`.

- Epic: [#314](https://github.com/wesleysimplicio/simplicio-agent/issues/314)
- Transactional self-mutation kernel: [#315](https://github.com/wesleysimplicio/simplicio-agent/issues/315)
- Source/release to live-bot updater: [#316](https://github.com/wesleysimplicio/simplicio-agent/issues/316)
- L0-L3 token governor: [#317](https://github.com/wesleysimplicio/simplicio-agent/issues/317)
- Prompt microkernel: [#318](https://github.com/wesleysimplicio/simplicio-agent/issues/318)
- Always-hot Rust daemon: [#319](https://github.com/wesleysimplicio/simplicio-agent/issues/319)
- Physics-based adaptive controller: [#320](https://github.com/wesleysimplicio/simplicio-agent/issues/320)
- Native gateway and isolated bridge: [#321](https://github.com/wesleysimplicio/simplicio-agent/issues/321)
- Full native namespace/identity migration: [#322](https://github.com/wesleysimplicio/simplicio-agent/issues/322)
- Final release and live-update gate: [#323](https://github.com/wesleysimplicio/simplicio-agent/issues/323)

Identity migration issues [#186](https://github.com/wesleysimplicio/simplicio-agent/issues/186) and [#117](https://github.com/wesleysimplicio/simplicio-agent/issues/117) are subordinate to #322; their former permanent-internal-legacy policy is superseded.
