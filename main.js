// main.js (modular entry point)
const { app } = require('electron');
const path = require('path');
const { createWindow, getMainWindow, createSettingsWindow, createHistoryWindow, createFileTranscribeWindow, navigateToHome, navigateToDictation, navigateToFileTranscribe } = require('./electron/electron_windows');
const { createTrayIcon } = require('./electron/electron_tray');
const { initializeIpcHandlers } = require('./electron/electron_ipc');
const { setupAppLifecycle } = require('./electron/electron_lifecycle');
const { createAppMenu } = require('./electron/electron_menu');

function main() {
  // Setup app lifecycle handlers first
  setupAppLifecycle();

  app.whenReady().then(() => {
    // Set dock icon explicitly for macOS dev mode
    if (process.platform === 'darwin') {
      const iconPath = path.join(__dirname, 'assets/app-icon.png');
      app.dock.setIcon(iconPath);
    }

    // Set up application menu bar
    createAppMenu({
      createSettingsWindow,
      createHistoryWindow,
      createFileTranscribeWindow,
      getMainWindow,
      navigateToHome,
      navigateToDictation,
      navigateToFileTranscribe
    });

    createWindow();
    initializeIpcHandlers();
    setTimeout(() => {
      createTrayIcon(getMainWindow, createSettingsWindow, createHistoryWindow, app, createFileTranscribeWindow);
    }, 300);
  });
}

// Call the main function to start the app logic
main();
