// electron_windows.js
// Handles main window and settings window management

const { BrowserWindow, ipcMain, screen } = require('electron');
const path = require('path');
const { startPythonBackend } = require('./electron_python');
const { store } = require('./electron_app_init');
const handyUiConstants = require('../frontend/shared/handy_ui_constants.json');

let mainWindow = null;

const CLASSIC_WINDOW_BOUNDS = {
  width: 700,
  height: 500,
  xOffset: 60,
  yOffset: 60
};

const HOME_WINDOW_BOUNDS = {
  width: 600,
  height: 480,
  xOffset: 100,
  yOffset: 80
};

const HANDY_WINDOW_BOUNDS = {
  width: Number.isFinite(Number(handyUiConstants.width)) ? Number(handyUiConstants.width) : 172,
  height: Number.isFinite(Number(handyUiConstants.height)) ? Number(handyUiConstants.height) : 36,
  bottomOffset: Number.isFinite(Number(handyUiConstants.bottomOffset)) ? Number(handyUiConstants.bottomOffset) : 28
};

let currentUiMode = 'classic';
let currentView = 'home'; // 'home', 'dictation', or 'filetranscribe'

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
    normalizedMode === 'handy' ? HANDY_WINDOW_BOUNDS.width : 500,
    normalizedMode === 'handy' ? HANDY_WINDOW_BOUNDS.height : 300
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

function isShowingHome() {
  return currentView === 'home';
}

function navigateToDictation() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  currentView = 'dictation';
  mainWindow.loadFile(path.join(__dirname, '../frontend/main/index.html'))
    .then(() => {
      console.log('[Nav] Navigated to dictation view');
      applyMainWindowUiMode(currentUiMode);
    })
    .catch((error) => {
      console.error('[Nav] Failed to navigate to dictation:', error);
    });
}

function navigateToFileTranscribe() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  currentView = 'filetranscribe';
  mainWindow.loadFile(path.join(__dirname, '../frontend/filetranscribe/filetranscribe.html'))
    .then(() => {
      console.log('[Nav] Navigated to file transcribe view');
    })
    .catch((error) => {
      console.error('[Nav] Failed to navigate to file transcribe:', error);
    });
}

function navigateToHome() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  currentView = 'home';
  mainWindow.loadFile(path.join(__dirname, '../frontend/home/home.html'))
    .catch((error) => {
      console.error('[Nav] Failed to navigate to home:', error);
    });
}

function createWindow() {
  currentUiMode = normalizeUiMode(store.get('uiMode', 'classic'));

  // Home page gets its own compact size
  const display = getDisplayForBounds();
  const workArea = display.workArea;

  mainWindow = new BrowserWindow({
    width: Math.min(HOME_WINDOW_BOUNDS.width, workArea.width),
    height: Math.min(HOME_WINDOW_BOUNDS.height, workArea.height),
    x: workArea.x + HOME_WINDOW_BOUNDS.xOffset,
    y: workArea.y + HOME_WINDOW_BOUNDS.yOffset,
    minWidth: 420,
    minHeight: 360,
    frame: true,
    transparent: false,
    backgroundColor: '#0c111a',
    title: 'OpenScribe',
    hasShadow: true,
    resizable: true,
    maximizable: true,
    minimizable: true,
    icon: path.join(__dirname, '../assets/app-icon.png'),
    webPreferences: {
      preload: path.join(__dirname, '../frontend/main/preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      devTools: true
    },
    show: false
  });

  // Load the home launcher page first
  currentView = 'home';
  mainWindow.loadFile(path.join(__dirname, '../frontend/home/home.html'))
    .then(() => {
      console.log('[Nav] home.html loaded');
    })
    .catch((error) => {
      console.error('[Nav] Failed to load home.html:', error);
    });

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  // Navigation IPC handlers
  ipcMain.on('home:open-live-dictation', () => {
    navigateToDictation();
  });

  ipcMain.on('home:open-file-transcribe', () => {
    navigateToFileTranscribe();
  });

  ipcMain.on('home:open-settings', () => {
    createSettingsWindow();
  });

  ipcMain.on('nav:go-home', () => {
    navigateToHome();
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
        width: currentBounds.width,
        height: Math.round(height)
      }, true);
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
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
    if (section) {
      settingsWindow.webContents.send('navigate-to-section', section);
    }
    return;
  }

  settingsWindow = new BrowserWindow({
    width: 800,
    height: 600,
    title: 'OpenScribe Settings',
    icon: path.join(__dirname, '../assets/app-icon.png'),
    webPreferences: {
      preload: path.join(__dirname, '../frontend/settings/settings_preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      devTools: true
    },
    show: false
  });

  settingsWindow.loadFile(path.join(__dirname, '../frontend/settings/settings.html'));

  settingsWindow.once('ready-to-show', () => {
    settingsWindow.show();
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

// File transcribe window kept for standalone launch from tray/menu
let fileTranscribeWindow = null;

function createFileTranscribeWindow() {
  // If main window is visible, navigate in-place instead
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.show();
    navigateToFileTranscribe();
    return mainWindow;
  }

  // Fallback: standalone window (e.g., if main window was closed)
  if (fileTranscribeWindow) {
    fileTranscribeWindow.focus();
    return fileTranscribeWindow;
  }

  fileTranscribeWindow = new BrowserWindow({
    width: 800,
    height: 640,
    title: 'Transcribe File',
    icon: path.join(__dirname, '../assets/app-icon.png'),
    minWidth: 600,
    minHeight: 400,
    webPreferences: {
      preload: path.join(__dirname, '../frontend/filetranscribe/filetranscribe_preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      devTools: true
    },
    show: false
  });

  fileTranscribeWindow.loadFile(path.join(__dirname, '../frontend/filetranscribe/filetranscribe.html'))
    .catch((error) => {
      console.error('[FileTranscribeWindow] Failed to load filetranscribe.html:', error);
    });

  fileTranscribeWindow.once('ready-to-show', () => {
    fileTranscribeWindow.show();
  });

  fileTranscribeWindow.on('closed', () => {
    fileTranscribeWindow = null;
  });

  return fileTranscribeWindow;
}

module.exports = {
  createWindow,
  getMainWindow,
  createSettingsWindow,
  createHistoryWindow,
  createFileTranscribeWindow,
  applyMainWindowUiMode,
  getCurrentUiMode,
  navigateToDictation,
  navigateToFileTranscribe,
  navigateToHome,
  isShowingHome
};
