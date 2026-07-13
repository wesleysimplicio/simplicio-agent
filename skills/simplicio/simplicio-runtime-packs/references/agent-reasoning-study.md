# Estudo de Raciocínio — Claude Code, Codex, OpenCode

Data: 2026-07-04
Método: deleguei tasks para cada agente via CLI perguntando como eles raciocinam.

## OpenCode
- **Fase Zero:** mapeamento contextual antes de qualquer ação (SO, diretório, ferramentas)
- **Decomposição:** "navalha de Occam programática" — pedido mais simples que resolve
- **Paralelismo:** máximo possível, nunca limitar
- **Tratamento de erros em 3 níveis:** esperado (automático), inesperado recuperável (retry), bloqueante (reportar erro REAL)
- **"Fail fast, recover loud"** — nunca inventar alternativa quando falha

## Claude Code
- **Reconhecimento:** nunca assume estrutura do projeto — explora primeiro
- **Modelo mental:** toolchain → arquitetura → entrypoints → dependências
- **Decisões:** "reversíveis primeiro" — priorizar o que é fácil de desfazer
- **Consistência sobre elegância:** código consistente > código "bonito"
- **Padrão:** exploração → plano → execução → verificação → iteração

## Codex
- **Reconhecimento em camadas:**
  - Camada 1: estrutura (5-10s)
  - Camada 2: contratos (configs)
  - Camada 3: entrypoints
  - Camada 4: testes representativos
- **Priorização por:** dependências → risco → valor de entrega
- **Testes como documentação viva** — código diz o que faz, teste diz o que DEVERIA fazer

## Convergência (todos os 3 fazem igual)
- Mapear antes de agir
- Errar cedo e honestamente (tracebacks reais, não simulações)
- Verificar cada passo — nunca assumir que funcionou
- Iterar até resultado final exercitado e visível
- Entregar conciso: ação real + resultado real
