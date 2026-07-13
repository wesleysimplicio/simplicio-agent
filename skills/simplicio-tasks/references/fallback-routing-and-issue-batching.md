# Fallback routing and issue batching

Este guia registra um padrão reaproveitável para tarefas grandes que cruzam várias superfícies do Simplicio/Hermes.

## Quando abrir múltiplas issues
Abra issues separadas quando a mudança toca classes diferentes de problema:
- bootstrap/binário/PATH
- cobertura MCP e roteamento de capacidades
- bridges de alta frequência (browser, computer-use, savings)
- bridges de cauda longa (cron, gateway, workflow, issue-factory, etc.)
- política de orientação/execução (Hermes-native-first vs runtime-first)

## Como dividir
Para cada issue:
1. Nome claro e orientado a domínio.
2. Corpo com fases curtas.
3. Checklist de critérios de aceitação.
4. Referências a arquivos/issue links reais.
5. Escopo pequeno o bastante para um subagent trabalhar sozinho.

## Fan-out paralelo
- Um subagent por issue quando as áreas não compartilham arquivo.
- Se houver arquivos compartilhados, agrupe por arquivo para evitar conflito.
- Feche só após validar o caminho feliz com comando real.

## Fallback honesto
Se a surface nativa/MCP esperada não estiver exposta na sessão atual:
- diga isso explicitamente;
- use CLI/nativa verificada como fallback;
- continue o trabalho em vez de travar;
- registre a lacuna como issue de melhoria.
