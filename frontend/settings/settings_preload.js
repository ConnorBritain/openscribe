const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('settingsAPI', {
  // Example function to send data to main process
  saveSettings: (settings) => ipcRenderer.send('save-settings', settings),

  // Example function to request settings from main process
  loadSettings: () => ipcRenderer.invoke('load-settings'),

  ensureModel: (modelId) => ipcRenderer.invoke('ensure-model', modelId),

  listMicrophones: () => ipcRenderer.invoke('list-microphones'),

  getAudioSources: () => ipcRenderer.invoke('audio:get-sources'),

  setHotkeysSuspended: (suspended) => ipcRenderer.invoke('set-hotkeys-suspended', !!suspended),

  // Function to call vocabulary API
  callVocabularyAPI: (command, data = {}) => ipcRenderer.invoke('vocabulary-api', command, data),

  // API key management
  getApiKeyStatus: () => ipcRenderer.invoke('apikey:status'),
  saveApiKey: (provider, value) => ipcRenderer.invoke('apikey:save', { provider, value }),
  deleteApiKey: (provider) => ipcRenderer.invoke('apikey:delete', { provider }),
  // Listen for navigation requests
  onNavigateToSection: (callback) => ipcRenderer.on('navigate-to-section', callback)
});

console.log('Settings preload script loaded.');
