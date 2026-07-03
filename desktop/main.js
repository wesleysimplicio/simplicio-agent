const { app, BrowserWindow, ipcMain } = require('electron');
const { exec } = require('child_process');
const path = require('path');

let mainWindow;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200, height: 800,
    webPreferences: { nodeIntegration: true, contextIsolation: false },
    icon: path.join(__dirname, 'icon.png'),
    titleBarStyle: 'hiddenInset',
  });
  mainWindow.loadFile('index.html');
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });

// IPC: rodar comando simplicio
ipcMain.handle('simplicio', async (_, cmd) => {
  return new Promise((resolve) => {
    exec(`simplicio ${cmd} --json 2>/dev/null`, (err, stdout) => {
      resolve(stdout || JSON.stringify({error: err?.message}));
    });
  });
});
