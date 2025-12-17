// main.js (modular entry point)
const { app } = require('electron');
const { createWindow, getMainWindow, createSettingsWindow, createHistoryWindow } = require('./electron/electron_windows');
const { createTrayIcon } = require('./electron/electron_tray');
const { initializeIpcHandlers } = require('./electron/electron_ipc');
const { setupAppLifecycle } = require('./electron/electron_lifecycle'); // Import lifecycle setup

function main() {
  // Setup app lifecycle handlers first
  setupAppLifecycle();
  
  app.whenReady().then(() => {
    createWindow();
    initializeIpcHandlers();
    setTimeout(() => {
      createTrayIcon(getMainWindow, createSettingsWindow, createHistoryWindow, app);
    }, 300);
  });
}

// Call the main function to start the app logic
main();
