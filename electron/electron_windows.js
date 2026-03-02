// electron_windows.js
// Handles main window and settings window management

const { BrowserWindow, ipcMain, screen } = require('electron');
const path = require('path');
const { startPythonBackend } = require('./electron_python');
const { store } = require('./electron_app_init');
const handyUiConstants = require('../frontend/shared/handy_ui_constants.json');

let mainWindow = null;
// No separate proofing window in note-only mode

const CLASSIC_WINDOW_BOUNDS = {
  width: 600,
  height: 120,
  xOffset: 20,
  yOffset: 20
};

const HANDY_WINDOW_BOUNDS = {
  width: Number.isFinite(Number(handyUiConstants.width)) ? Number(handyUiConstants.width) : 172,
  height: Number.isFinite(Number(handyUiConstants.height)) ? Number(handyUiConstants.height) : 36,
  bottomOffset: Number.isFinite(Number(handyUiConstants.bottomOffset)) ? Number(handyUiConstants.bottomOffset) : 28
};

let currentUiMode = 'classic';

function normalizeUiMode(mode) {
  return mode === 'handy' ? 'handy' : 'classic';
}

function getDisplayForBounds(bounds = null) {
  try {
    if (bounds) {
      return screen.getDisplayMatching(bounds) || screen.getPrimaryDisplay();
    }
    return screen.getDisplayNearestPoint(screen.getCursorScreenPoint()) || screen.getPrimaryDisplay();
  } catch (_error) {
    return screen.getPrimaryDisplay();
  }
}

function getBoundsForMode(mode, referenceBounds = null) {
  const normalizedMode = normalizeUiMode(mode);
  const display = getDisplayForBounds(referenceBounds);
  const workArea = display.workArea;

  if (normalizedMode === 'handy') {
    const width = Math.min(HANDY_WINDOW_BOUNDS.width, workArea.width);
    const height = Math.min(HANDY_WINDOW_BOUNDS.height, workArea.height);
    return {
      width,
      height,
      x: Math.round(workArea.x + (workArea.width - width) / 2),
      y: Math.round(workArea.y + workArea.height - height - HANDY_WINDOW_BOUNDS.bottomOffset)
    };
  }

  const width = Math.min(CLASSIC_WINDOW_BOUNDS.width, workArea.width);
  const height = Math.min(CLASSIC_WINDOW_BOUNDS.height, workArea.height);
  return {
    width,
    height,
    x: workArea.x + CLASSIC_WINDOW_BOUNDS.xOffset,
    y: workArea.y + CLASSIC_WINDOW_BOUNDS.yOffset
  };
}

function getCurrentUiMode() {
  return currentUiMode;
}

function applyMainWindowUiMode(mode) {
  const normalizedMode = normalizeUiMode(mode);
  currentUiMode = normalizedMode;

  if (!mainWindow || mainWindow.isDestroyed()) {
    return normalizedMode;
  }

  const nextBounds = getBoundsForMode(normalizedMode, mainWindow.getBounds());
  mainWindow.setResizable(normalizedMode !== 'handy');
  mainWindow.setMinimumSize(
    normalizedMode === 'handy' ? HANDY_WINDOW_BOUNDS.width : 420,
    normalizedMode === 'handy' ? HANDY_WINDOW_BOUNDS.height : 90
  );
  mainWindow.setBackgroundColor(normalizedMode === 'handy' ? '#00000000' : '#0c111a');
  if (typeof mainWindow.setHasShadow === 'function') {
    mainWindow.setHasShadow(normalizedMode !== 'handy');
  }
  mainWindow.setBounds(nextBounds, true);

  if (mainWindow.webContents && !mainWindow.webContents.isDestroyed()) {
    mainWindow.webContents.send('ui-mode-updated', { uiMode: normalizedMode });
  }

  return normalizedMode;
}

function createWindow() {
  currentUiMode = normalizeUiMode(store.get('uiMode', 'classic'));
  const initialBounds = getBoundsForMode(currentUiMode);

  mainWindow = new BrowserWindow({
    width: initialBounds.width,
    height: initialBounds.height,
    x: initialBounds.x,
    y: initialBounds.y,
    minWidth: currentUiMode === 'handy' ? HANDY_WINDOW_BOUNDS.width : 420,
    minHeight: currentUiMode === 'handy' ? HANDY_WINDOW_BOUNDS.height : 90,
    frame: false,
    transparent: true,
    backgroundColor: currentUiMode === 'handy' ? '#00000000' : '#0c111a',
    hasShadow: currentUiMode !== 'handy',
    resizable: currentUiMode !== 'handy',
    icon: path.join(__dirname, '../assets/app-icon.png'),
    webPreferences: {
      preload: path.join(__dirname, '../frontend/main/preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      devTools: true // Enable DevTools for debugging
    },
    show: true // Show immediately for debugging
  });

  // Load the main window
  const htmlPath = path.join(__dirname, '../frontend/main/index.html');
  console.log('[DEBUG] Loading index.html from:', htmlPath);
  mainWindow.loadFile(htmlPath)
    .then(() => {
      console.log('[DEBUG] index.html loaded successfully');
    })
    .catch((error) => {
      console.error('[ERROR] Failed to load index.html:', error);
    });

  // Show main window after it's loaded (keeping this for when we re-enable proper show)
  mainWindow.once('ready-to-show', () => {
    console.log('[DEBUG] ready-to-show event fired');
    mainWindow.show();
    applyMainWindowUiMode(currentUiMode);
  });

  // IPC handler for resizing the main window from the renderer
  ipcMain.on('resize-window', (event, { height }) => {
    if (currentUiMode === 'handy') {
      return;
    }
    if (mainWindow && height) {
      const currentBounds = mainWindow.getBounds();
      mainWindow.setBounds({
        x: currentBounds.x,
        y: currentBounds.y,
        width: currentBounds.width, // Keep current width
        height: Math.round(height)
      }, true); // Animate the resize
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
    // No proofingWindow to close anymore
  });

  // Start Python backend when the window is ready
  startPythonBackend(mainWindow);
}

function getMainWindow() {
  return mainWindow;
}


let settingsWindow = null;
let historyWindow = null;

function createSettingsWindow(section = null) {
  if (settingsWindow) {
    settingsWindow.focus();
    // If a section is specified and window already exists, navigate to that section
    if (section) {
      settingsWindow.webContents.send('navigate-to-section', section);
    }
    return;
  }

  settingsWindow = new BrowserWindow({
    width: 800,
    height: 600,
    title: 'Citrix Transcriber Settings',
    icon: path.join(__dirname, '../assets/app-icon.png'),
    webPreferences: {
      preload: path.join(__dirname, '../frontend/settings/settings_preload.js'), // Assuming a settings_preload.js for settings IPC
      contextIsolation: true,
      nodeIntegration: false,
      devTools: true // Enable DevTools for settings window for easier debugging
    },
    show: false // Don't show until ready
  });

  settingsWindow.loadFile(path.join(__dirname, '../frontend/settings/settings.html'));

  settingsWindow.once('ready-to-show', () => {
    settingsWindow.show();
    // If a section is specified, navigate to it after the window is ready
    if (section) {
      settingsWindow.webContents.send('navigate-to-section', section);
    }
  });

  settingsWindow.on('closed', () => {
    settingsWindow = null;
  });
}

function createHistoryWindow() {
  if (historyWindow) {
    historyWindow.focus();
    return historyWindow;
  }

  historyWindow = new BrowserWindow({
    width: 960,
    height: 640,
    title: 'Dictation History',
    icon: path.join(__dirname, '../assets/app-icon.png'),
    minWidth: 720,
    minHeight: 480,
    webPreferences: {
      preload: path.join(__dirname, '../frontend/history/history_preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      devTools: true
    },
    show: false
  });

  historyWindow.loadFile(path.join(__dirname, '../frontend/history/history.html'))
    .catch((error) => {
      console.error('[HistoryWindow] Failed to load history.html:', error);
    });

  historyWindow.once('ready-to-show', () => {
    historyWindow.show();
  });

  historyWindow.on('closed', () => {
    historyWindow = null;
  });

  return historyWindow;
}

module.exports = {
  createWindow,
  getMainWindow,
  createSettingsWindow,
  createHistoryWindow,
  applyMainWindowUiMode,
  getCurrentUiMode
};
