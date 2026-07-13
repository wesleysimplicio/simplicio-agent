# Discord Channel Prompts (Hermes Gateway)

## Pattern: Per-Project Channels with Dedicated Prompts

O Hermes suporta channel prompts — system prompts específicos por canal
Discord. Cada canal pode ter um agente com contexto e personalidade
diferentes, tudo com o **mesmo bot**.

## Configuração (config.yaml — default profile, Junho 2026)

16 canais ativos, 3 com prompt dedicado:

```yaml
discord:
  require_mention: false
  free_response_channels: >-
    1514963053492437156,1514946462222647307,1478128143029112950,
    1508172718800113816,1508172720955723940,
    1507851184377958441,1507851187733397634,1507851189687943329,
    1507857271932059690,1507851191541829684,1507857273773625428,
    1507851193496633574,1507851196550090843,1507857276910960761,
    1507851198395580588,1507857278718447646
  allowed_channels: >-     # mesma lista acima
  auto_thread: true
  thread_require_mention: false
  history_backfill: true
  history_backfill_limit: 50
  reactions: true
  channel_prompts:
    '1514946462222647307': |
      #simplicio-runtime — agente especializado no projeto Simplicio
      - Repositório: /Users/wesleysimplicio/Projetos/ai/simplicio-runtime/
      - Binário compilado: ./target/release/simplicio
      - Use `simplicio runtime map --repo . --for-llm markdown`
      - Rust, TUI (ratatui), auto-update
      - Responda em português, direto e prático
    '1508172718800113816': |
      #hermes — especialista em contribuição para Hermes Agent
      - Repositório: /Users/wesleysimplicio/Projetos/ai/hermes-agent/
      - Faça git pull da main antes de começar
      - Code review, issues, PRs, discussões de arquitetura
      - Siga CONTRIBUTING.md
      - Responda em português
    '1508172720955723940': |
      #brasil — especialista em tecnologia financeira brasileira
      - Open Finance Brasil, Pix, Boletos, Pagamentos
      - APIs: BB, Inter, PagBank, BTG, PicPay, Matera
      - Foco em soluções para o mercado brasileiro
      - Responda em português
```

## Regras

1. **1 bot token = 1 gateway.** Nunca rodar dois perfis Hermes no Discord
   com o mesmo token. Apenas o perfil default deve rodar o gateway.
   Se um segundo gateway for descoberto, parar e desativar:
   ```bash
   launchctl bootout gui/$(id -u)/ai.hermes.gateway-simplicio
   mv ~/Library/LaunchAgents/ai.hermes.gateway-simplicio.plist \
      ~/Library/LaunchAgents/ai.hermes.gateway-simplicio.plist.disabled
   ```
2. `allowed_channels` — whitelist de canais que o bot monitora.
3. `free_response_channels` — canais que respondem sem @mention.
4. `channel_prompts` pode ser gerenciado via CLI ou YAML:
   ```bash
   # CLI (preferido — não precisa editar YAML manualmente)
   hermes config set discord.channel_prompts.<ID> "prompt text"
   hermes config set discord.allowed_channels "id1,id2,..."
   hermes config set discord.free_response_channels "id1,id2,..."
   ```

## Troubleshooting

### Bot não responde em NENHUM canal

1. Conferir se o gateway está rodando: `launchctl print gui/$(id -u)/ai.hermes.gateway | grep state`
2. Verificar se o Discord está conectado: `cat ~/.hermes/gateway_state.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['platforms']['discord']['state'])"`
3. Confirmar channel IDs estão corretos via API: `send_message action=list`
4. Verificar `require_mention` — se true, precisa de @mention
5. Logs: `tail -30 ~/.hermes/logs/gateway.log | grep -E "inbound|Sending response"`

### Bot responde SÓ em UM canal (outros ignorados)

Causa mais comum: o canal mudo **não está em `allowed_channels`**. O bot
enxerga todos os canais do servidor, mas só responde nos que estão na
whitelist.

```bash
# Verificar canais que o bot enxerga
send_message action=list

# Verificar config atual
grep -A5 "allowed_channels" ~/.hermes/config.yaml
```

**Fix:** adicionar o channel ID em `allowed_channels` e `free_response_channels`
no `config.yaml`. IDs são strings separadas por vírgula.

Exemplo para ativar TODOS os canais do Simple TI:
```yaml
discord:
  allowed_channels: '1514963053492437156,1514946462222647307,1478128143029112950'
  free_response_channels: '1514963053492437156,1514946462222647307'
```

**Verificação após ajuste:** enviar mensagem no canal, chegar `grep "inbound message" ~/.hermes/logs/gateway.log` em segundos.

### Gateway duplicado

```bash
launchctl list | grep gateway
# Se houver mais de um:
launchctl bootout gui/$(id -u)/ai.hermes.gateway-NOME
mv ~/Library/LaunchAgents/ai.hermes.gateway-NOME.plist \
   ~/Library/LaunchAgents/ai.hermes.gateway-NOME.plist.disabled
```
