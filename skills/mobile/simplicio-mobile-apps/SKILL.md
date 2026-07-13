---
name: simplicio-mobile-apps
description: "Mobile apps integration for Simplicio — ngrok tunnel, QR pairing, push notifications via Expo, and remote device management via OpenCode mobile bridge."
version: 1.0.0
author: Wesley Simplicio
license: MIT
platforms: [macos]
prerequisites:
  commands: [ngrok]
  env: [NGROK_AUTHTOKEN]
---

# Simplicio Mobile Apps

Integração mobile para o Simplicio. Permite conectar dispositivos via QR code, receber notificações push, e gerenciar o bot remotamente.

## Componentes

### 1. Ngrok Tunnel (rodando)
```
URL: https://foyer-marmalade-ethically.ngrok-free.dev
Porta local: 80
Authtoken configurado ✅
```

### 2. OpenCode Mobile Bridge
Instalado em `~/.config/opencode/commands/mobile.md`

Plugin registrado: `opencode-mobile@latest`

### 3. Script de Tunnel Mobile

```bash
#!/usr/bin/env bash
# ~/.hermes/scripts/simplicio-tunnel.sh
# Garante que o ngrok esteja sempre rodando

TUNNEL_NAME="simplicio-mobile"
NGROK_URL="https://foyer-marmalade-ethically.ngrok-free.dev"

# Verifica se o túnel está ativo
if ! curl -sf http://127.0.0.1:4040/api/tunnels > /dev/null 2>&1; then
  echo "Túnel caído. Reiniciando..."
  ngrok http --url="$NGROK_URL" 80 --log=stdout > /dev/null 2>&1 &
  disown
  echo "Túnel reiniciado: $NGROK_URL"
else
  echo "Túnel OK: $NGROK_URL"
fi
```

## Comandos Simplicio

| Comando | Descrição |
|---------|-----------|
| `/mobile qr` | Exibe QR code para parear dispositivo |
| `/mobile status` | Mostra status do túnel e conexões |
| `/mobile restart` | Reinicia o túnel ngrok |
| `/mobile notify <mensagem>` | Envia notificação push para dispositivos pareados |

##API de Notificação

```bash
# Enviar notificação via Expo Push
curl -X POST https://exp.host/--/api/v2/push/send \
  -H "Content-Type: application/json" \
  -d '{
    "to": "<ExponentPushToken>",
    "title": "Simplicio",
    "body": "Mensagem do bot"
  }'
```

## Fluxo de Pareamento

1. Usuário envia `/mobile` no Discord
2. Simplicio gera QR code com URL do túnel
3. Usuário escaneia com o app mobile
4. Dispositivo registra push token
5. Simplicio confirma pareamento

## Referências

- OpenCode Mobile: https://github.com/doza62/opencode-mobile
- Ngrok Dashboard: https://dashboard.ngrok.com
- Expo Push API: https://docs.expo.dev/push-notifications/sending-notifications/
