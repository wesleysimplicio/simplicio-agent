// Simplicio System Tray — Ícone na barra de menus do macOS
const { Tray, Menu, nativeImage, app, BrowserWindow } = require('electron')
const path = require('node:path')
const fs = require('node:fs')

let tray = null

const ICON_SIZE = 22 // tamanho padrão do menu bar do macOS

function getTrayIcon(status) {
  const iconPath = path.join(__dirname, '..', 'build', `icon-${ICON_SIZE * 2}.png`)
  if (fs.existsSync(iconPath)) {
    const img = nativeImage.createFromPath(iconPath)
    // macOS menu bar icons should be template images (respect dark/light mode)
    img.setTemplateImage(true)
    return img.resize({ width: ICON_SIZE, height: ICON_SIZE })
  }
  return nativeImage.createEmpty()
}

function createTray(mainWindow) {
  if (tray) return

  const icon = getTrayIcon('active')
  tray = new Tray(icon)
  tray.setToolTip('Simplicio Agent — 💚 Ativo')

  const contextMenu = Menu.buildFromTemplate([
    {
      label: '💚 Simplicio Agent',
      enabled: false,
    },
    { type: 'separator' },
    {
      label: 'Abrir Simplicio',
      click: () => {
        if (mainWindow) {
          mainWindow.show()
          mainWindow.focus()
        }
      },
    },
    {
      label: 'Token Monitor',
      click: () => {
        if (mainWindow) {
          mainWindow.webContents.send('navigate', '/monitor')
          mainWindow.show()
          mainWindow.focus()
        }
      },
    },
    { type: 'separator' },
    {
      label: 'Configurações',
      click: () => {
        if (mainWindow) {
          mainWindow.webContents.send('navigate', '/settings')
          mainWindow.show()
          mainWindow.focus()
        }
      },
    },
    { type: 'separator' },
    {
      label: 'Sair',
      click: () => {
        app.quit()
      },
    },
  ])

  tray.setContextMenu(contextMenu)

  tray.on('click', () => {
    if (mainWindow) {
      mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show()
    }
  })

  return tray
}

function updateTrayStatus(status) {
  if (!tray) return
  const icon = getTrayIcon(status)
  tray.setImage(icon)

  const labels = { active: '💚 Ativo', paused: '⏸️ Pausado', offline: '❌ Offline' }
  tray.setToolTip(`Simplicio Agent — ${labels[status] || labels.active}`)
}

function destroyTray() {
  if (tray) {
    tray.destroy()
    tray = null
  }
}

module.exports = { createTray, updateTrayStatus, destroyTray }
