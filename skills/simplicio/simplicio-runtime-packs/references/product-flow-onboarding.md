# Product Flow & Onboarding (05/07/2026)

Fluxo completo do usuário, da instalação ao uso contínuo.

## 1. Instalação (30s)
1. Baixa `.dmg` de simplicio.agent → arrasta pra Applications
2. Primeira abertura → Tami guia onboarding
3. Login/cadastro (email + senha) → 7 dias grátis → R$99/mês

## 2. Onboarding (2min)
1. Tami se apresenta: "💚 Oi! Isa guarda memória, Helo executa, Levi busca"
2. Wake word "Simplicio" ativado — escuta sempre, acorda só quando chamado
3. Primeiro comando (texto ou voz): tour das capabilities

## 3. Uso Diário
- **Voz**: "Simplicio" → Parakeet STT (4x whisper) → DeepSeek → Tami responde
- **Texto**: Chat direto → DeepSeek V4 Flash → Simplicio Runtime executa
- **Pró-ativo**: Tami aparece a cada 1h com sugestões

## 4. Arquitetura
```
Desktop App (Electron) → MCP stdio → Simplicio Runtime (Rust)
                                     → DeepSeek V4 Flash
                                     → Tami + Isa + Helo + Levi
```

## 5. Tray + Token Monitor
- **Tray**: Ícone na barra 💚 ativo / ⏸️ pausado / ❌ offline
  - Clique → abre/fecha janela
  - Menu: Abrir · Token Monitor · Config · Sair
- **Token Monitor**: Tokens usados hoje, limite, custo estimado

## 6. Desktop Config (electron-builder)
- macOS: `.dmg` (arm64 + x64), hardened runtime
- Windows: `.exe` (NSIS) + `.msi`
- Linux: `.AppImage` + `.deb` + `.rpm`
- Icons: `desktop/build/icon-{64,256,512,1024}.png`

## 7. Arquivos
- `desktop/electron/tray.cjs` — SystemTray com Simplicio branding
- `desktop/src/TokenMonitor.tsx` — Dashboard de uso de tokens
- `desktop/electron.vite.config.ts` — Build config electron-vite
- `desktop/electron/main.cjs` — Tray integrado após `mainWindow.show()`
