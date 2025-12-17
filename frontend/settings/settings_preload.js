const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('settingsAPI', {
  // Example function to send data to main process
  saveSettings: (settings) => ipcRenderer.send('save-settings', settings),

  // Example function to request settings from main process
  loadSettings: () => ipcRenderer.invoke('load-settings'),

  ensureModel: (modelId) => ipcRenderer.invoke('ensure-model', modelId),

  // Function to call vocabulary API
  callVocabularyAPI: (command, data = {}) => ipcRenderer.invoke('vocabulary-api', command, data),

  // Listen for navigation requests
  onNavigateToSection: (callback) => ipcRenderer.on('navigate-to-section', callback)
});

console.log('Settings preload script loaded.');
