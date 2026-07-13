# Gateway Lifecycle Management

## Contexto

O gateway de mensageria (Hermes Gateway) é o processo que conecta o Simplicio Agent
a plataformas como Discord, Telegram, WhatsApp, etc. Em macOS, é gerenciado via
`launchd` com auto-restart em caso de crash.

## Comandos (via simplicio_agent, não hermes)

```bash
simplicio_agent gateway status      # Status do serviço launchd
simplicio_agent gateway list        # Lista gateways ativos
simplicio_agent gateway restart     # RESTART via launchd (funciona de fora)
```

## ⚠️ Não pode restartar de dentro do gateway

O comando `simplicio_agent gateway restart` **falha** se executado dentro da própria
sessão do gateway (bloqueio do Hermes: "cannot restart from inside the gateway process").

**Sintoma:**
```
Blocked: cannot restart or stop the gateway from inside the gateway process.
The gateway would kill this command before it could complete.
```

## Fluxo de restart manual (quando launchd não basta)

```bash
# 1. Identificar PIDs do gateway
ps aux | grep '[h]ermes.*gateway'

# 2. Matar com SIGKILL (SIGTERM pode não funcionar se o processo estiver travado)
kill -9 <PID1> <PID2>

# 3. launchd reinicia automaticamente em segundos
sleep 2
ps aux | grep '[h]ermes.*gateway'
# → Novo PID visível

# 4. Verificar status
simplicio_agent gateway status
```

## Launchd service

- **Plist:** `~/Library/LaunchAgents/ai.hermes.gateway.plist`
- **Auto-start:** Sim, no login
- **Auto-restart:** Sim, em crash
- **Atualização:** `simplicio_agent gateway start` recria o plist se necessário

## ⚠️ Voice messages e auto-resume

Durante restart do gateway, mensagens de voz (voice notes) podem ser perdidas:

- `inbound message: msg=''` aparece no log mas o áudio nunca é processado
- **Causa:** o auto-resume de sessão filtra/replay as mensagens, e voice messages com `msg=''` podem ser engolidas
- **Solução:** parar de reiniciar o gateway durante debug — deixar o processo stable. Enviar a voice message APÓS o gateway estar conectado e o auto-resume completo.
- **Confirmação:** verificar `~/.simplicio_agent/audio_cache/` — se o áudio for cacheado, a transcrição funciona. Se não aparecer, o voice message não chegou ao pipeline de attachments.

## Notas

- O gateway tem **auto-restart** via launchd. Matar o processo força restart limpo.
- Dois gateways podem coexistir (PID diferentes, mesmo comando) durante transição.
- `simplicio_agent` = alias de `hermes` CLI. Fora do gateway, ambos funcionam.
