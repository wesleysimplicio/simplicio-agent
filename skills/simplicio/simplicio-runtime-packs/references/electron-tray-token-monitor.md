# Desktop Tray + Token Monitor — Electron Pattern

## Tray Icon (electron/tray.cjs)

Adicionar SystemTray na barra de menus do macOS:

```js
// electron/tray.cjs
const { Tray, Menu, nativeImage, app } = require('electron')

function createTray(mainWindow) {
  const icon = nativeImage.createFromPath('build/icon-44.png')
  icon.setTemplateImage(true)
  
  const tray = new Tray(icon.resize({ width: 22, height: 22 }))
  tray.setToolTip('Simplicio Agent — 💚 Ativo')

  const menu = Menu.buildFromTemplate([
    { label: '💚 Simplicio Agent', enabled: false },
    { type: 'separator' },
    { label: 'Abrir', click: () => { mainWindow.show(); mainWindow.focus() } },
    { label: 'Token Monitor', click: () => mainWindow.webContents.send('navigate', '/monitor') },
    { type: 'separator' },
    { label: 'Sair', click: () => app.quit() },
  ])
  tray.setContextMenu(menu)
  tray.on('click', () => mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show())
}
```

## Token Monitor (src/TokenMonitor.tsx)

Componente React que mostra gráfico de uso de tokens:

```tsx
// Estado: { used: number, limit: number, cost: number }
// Barra de progresso com 3 zonas de cor:
//   < 50% → #22d3ee (cyan)
//   50-80% → #fb923c (laranja)
//   > 80% → #ef4444 (vermelho)

// Cards de período: Hoje / 7 dias / 30 dias
// Refresh automático a cada 30s
```

## Integração no main.cjs

```js
// 1. Require no topo
const { createTray, destroyTray } = require('./tray.cjs')

// 2. Criar após window.show()
mainWindow.once('ready-to-show', () => {
  mainWindow.show()
  createTray(mainWindow)  // ← adicionar aqui
})

// 3. Destruir no quit
app.on('will-quit', () => {
  destroyTray()
})
```
