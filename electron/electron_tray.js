// electron_tray.js
// Handles tray icon management and menu actions

const { Tray, Menu, nativeImage, app, ipcMain } = require('electron');
const path = require('path');
const { store } = require('./electron_app_init');

function getTrayIconPath(iconName) {
  // In packaged app, use app.getAppPath() to get the correct resource path
  // In development, go up one level from electron/ to project root
  if (app.isPackaged) {
    // For packaged app, icons are in the asar file
    return path.join(app.getAppPath(), iconName);
  } else {
    // For development, icons are in the project directory (go up from electron/ to root)
    return path.join(__dirname, '..', iconName);
  }
}

const trayIconPaths = {
  green: getTrayIconPath('assets/icon-green.png'),
  orange: getTrayIconPath('assets/icon-orange.png'),
  blue: getTrayIconPath('assets/icon-blue.png'),
  grey: getTrayIconPath('assets/icon-grey.png')
};

// Pre-load and cache all tray icons to prevent flashing
let trayIcons = {};
let tray = null;
let trayContextDeps = null;

function isWakeWordEnabled() {
  return store.get('wakeWordEnabled', true) !== false;
}

function toggleWakeWordFromTray() {
  const nextEnabled = !isWakeWordEnabled();
  if (ipcMain.listenerCount('set-wake-word-enabled') === 0) {
    console.error('[Tray] Wake word IPC handler not initialized.');
    return;
  }
  ipcMain.emit('set-wake-word-enabled', null, nextEnabled);
}

function buildContextMenu() {
  if (!trayContextDeps) {
    return Menu.buildFromTemplate([]);
  }

  const wakeWordLabel = isWakeWordEnabled() ? 'Wake Word On' : 'Wake Word Off';
  const quitApp = trayContextDeps.app || app;

  return Menu.buildFromTemplate([
    {
      label: 'Start Dictation',
      click: () => {
        const { getPythonShell } = require('./electron_python');
        const pythonShell = getPythonShell();
        if (pythonShell) {
          pythonShell.send('start_dictate');
        } else {
          console.error('Tray Menu Error: Python backend not running.');
        }
      }
    },
    {
      label: wakeWordLabel,
      click: toggleWakeWordFromTray
    },
    { label: 'Settings...', accelerator: 'CmdOrCtrl+,', click: trayContextDeps.createSettingsWindow },
    { label: 'Vocabulary', click: () => trayContextDeps.createSettingsWindow('vocabulary') },
    { label: 'History…', click: trayContextDeps.createHistoryWindow },
    { type: 'separator' },
    { label: 'Show Floating UI', click: () => { const win = trayContextDeps.getMainWindow ? trayContextDeps.getMainWindow() : null; if (win) win.show(); } },
    { label: 'Quit Citrix Transcriber', accelerator: 'CmdOrCtrl+Q', click: () => { quitApp.quit(); } }
  ]);
}

function refreshTrayMenu() {
  if (!tray || !trayContextDeps) {
    return;
  }
  const contextMenu = buildContextMenu();
  tray.setContextMenu(contextMenu);
}

function preloadTrayIcons() {
  trayIcons = {
    green: nativeImage.createFromPath(trayIconPaths.green).resize({ width: 16, height: 16 }),
    orange: nativeImage.createFromPath(trayIconPaths.orange).resize({ width: 16, height: 16 }),
    blue: nativeImage.createFromPath(trayIconPaths.blue).resize({ width: 16, height: 16 }),
    grey: nativeImage.createFromPath(trayIconPaths.grey).resize({ width: 16, height: 16 })
  };
}

function setTrayIconByState(state) {
  if (!tray) return;
  let icon;
  switch (state) {
  case 'dictation':
    icon = trayIcons.green;
    break;
  case 'processing':
    icon = trayIcons.orange;
    break;
  case 'activation':
    icon = trayIcons.blue;
    break;
  case 'preparing':
  case 'inactive':
  default:
    icon = trayIcons.grey;
    break;
  }
  if (icon) {
    tray.setImage(icon);
  }
}

function createTrayIcon(getMainWindow, createSettingsWindow, createHistoryWindow, appInstance) {
  if (tray) {
    console.log('Tray icon already exists.');
    return;
  }

  trayContextDeps = {
    getMainWindow,
    createSettingsWindow,
    createHistoryWindow,
    app: appInstance
  };

  // Pre-load all tray icons to prevent flashing
  preloadTrayIcons();
  const iconPath = getTrayIconPath('assets/icon.png');
  let icon = nativeImage.createFromPath(iconPath);
  if (icon.isEmpty()) {
    console.error(`ERROR: Icon image loaded from path "${iconPath}" but is empty.`);
    return;
  }
  if (process.platform === 'darwin') {
    icon.setTemplateImage(true);
  }
  const resizedIcon = icon.resize({ width: 16, height: 16 });
  tray = new Tray(resizedIcon);

  // Set initial tray icon to grey immediately after creation
  console.log('[Tray] Setting initial tray icon to grey (inactive state)');
  tray.setImage(trayIcons.grey);

  refreshTrayMenu();
}

module.exports = { setTrayIconByState, createTrayIcon, refreshTrayMenu, tray };
