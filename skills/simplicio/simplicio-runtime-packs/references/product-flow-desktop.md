# Product Flow + Desktop App Launch Pattern

## Fluxo do Produto (definido 05/07/2026)

```
1. INSTALAÇÃO (30s)
   ╰→ Baixa .dmg → arrasta pra Applications → abre
   ╰→ Tami guia: login → 7 dias grátis → R$99/mês

2. ONBOARDING (2min)
   ╰→ Tami se apresenta (Isa/Helo/Levi)
   ╰→ Wake word "Simplicio" ativado
   ╰→ Primeiro comando: texto ou voz

3. USO DIÁRIO
   ╰→ 🎤 "Simplicio, quanto falta pro meu projeto?"
   ╰→ ⌨️ Chat direto com DeepSeek V4
   ╰→ 🔄 Tami aparece a cada 1h com sugestões

4. ARQUITETURA
   Desktop App (Electron) → MCP stdio → Simplicio Runtime (Rust)
                                      → DeepSeek V4 Flash
                                      → Tami + Isa + Helo + Levi

5. TRAY + TOKEN MONITOR
   ╰→ Ícone na barra: 💚 ativo / ⏸️ pausado / ❌ offline
   ╰→ Monitor: tokens usados hoje, limite, custo
```

## Desktop Tray (macOS)

`electron/tray.cjs` deve ser:
- Criado em `desktop/electron/tray.cjs`
- Requerido em `electron/main.cjs` (`const { createTray, destroyTray } = require('./tray.cjs')`)
- Inicializado após `mainWindow.show()` (no `ready-to-show` event)
- Destruído em `will-quit` handler

Tray menu template:
```js
Menu.buildFromTemplate([
  { label: '💚 Simplicio Agent', enabled: false },
  { type: 'separator' },
  { label: 'Abrir Simplicio', click: () => mainWindow.show() },
  { label: 'Token Monitor', click: () => mainWindow.webContents.send('navigate', '/monitor') },
  { type: 'separator' },
  { label: 'Sair', click: () => app.quit() },
])
```

## Token Monitor React Component

`src/TokenMonitor.tsx` — componente que:
- Busca `/v1/status` no runtime (porta 6119) a cada 30s
- Mostra tokens usados / limite / % / custo estimado
- Cards de "Hoje / 7 dias / 30 dias"

## Build Desktop .dmg (macOS)

### Vite ESM Error Workaround
Os plugins `@vitejs/plugin-react` e `@tailwindcss/vite` são ESM-only, mas o Vite CJS API tenta `require()`-los.

**Solução:** Converter `vite.config.ts` para `vite.config.mjs` + usar Node 26:
```bash
# 1. Renomear config
mv vite.config.ts vite.config.mjs

# 2. Usar Node 26 (Homebrew)
export PATH="/opt/homebrew/bin:$PATH"

# 3. Reinstalar node_modules com Node 26
rm -rf node_modules package-lock.json
npm install

# 4. Build
node --input-type=module -e "
import { build } from 'vite';
await build({ configFile: './vite.config.mjs' });
"
```

### electron-builder config
Pré-configurado em `desktop/package.json`:
- macOS: `.dmg` + `.zip` (arm64 + x64)
- Windows: `.exe` (NSIS) + `.msi` (x64)
- Linux: `.AppImage` + `.deb` + `.rpm` (x64)

## MCP Guide

`simplicio/MCP-CONNECT.md` — guia para conectar qualquer cliente (Claude, Cursor, VS Code):
```json
{ "mcpServers": { "simplicio": {
    "command": "simplicio",
    "args": ["serve", "--mcp", "--stdio"]
} } }
```

10 tools expostas: map, memory, edit, gate, validate, run, symbol, search, read, exec.
