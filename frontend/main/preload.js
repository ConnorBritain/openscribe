const { contextBridge, ipcRenderer, clipboard } = require('electron');

// Expose protected methods that allow the renderer process to use
// the ipcRenderer without exposing the entire object
contextBridge.exposeInMainWorld('electronAPI', {
  // Send data/commands to the Python backend via the main process
  sendToPython: (data) => ipcRenderer.send('to-python', data),

  // Receive messages from the Python backend (forwarded by main process)
  handleFromPython: (callback) => ipcRenderer.on('from-python', (_event, value) => callback(value)),

  // Receive stderr messages from the Python backend
  handlePythonStderr: (callback) => ipcRenderer.on('python-stderr', (_event, value) => callback(value)),

  // Send toggle always on top request to main process
  toggleAlwaysOnTop: (forceState) => ipcRenderer.send('toggle-always-on-top', forceState),

  // Send stop dictation request (process audio) to main process
  stopDictation: () => ipcRenderer.send('stop-dictation'),

  // Send abort dictation request (discard audio) to main process
  abortDictation: () => ipcRenderer.send('abort-dictation'),

  // Send tray state to main process for icon update
  sendTrayState: (state) => ipcRenderer.send('set-tray-state', state),

  // Toggle wake word listening preference
  setWakeWordEnabled: (enabled) => ipcRenderer.send('set-wake-word-enabled', enabled),

  // Send resize window request to main process
  resizeWindow: (data) => ipcRenderer.send('resize-window', data),

  // Call vocabulary API commands (e.g., learn corrections)
  vocabularyApi: (command, data = {}) => ipcRenderer.invoke('vocabulary-api', command, data),

  // Re-transcribe a history entry with a different ASR model
  retranscribe: (entryId, modelId) => ipcRenderer.invoke('history:retranscribe', entryId, modelId),

  // Re-paste text via clipboard
  repaste: (text) => ipcRenderer.send('repaste-text', text),

  // Load the current UI mode (classic or handy)
  loadUiMode: () => ipcRenderer.invoke('load-ui-mode'),

  // Load shared Handy UI constants (width/height/bar geometry)
  loadHandyUiConstants: () => ipcRenderer.invoke('load-handy-ui-constants'),

  // Load shared IPC contract schema (message prefixes + payload states)
  loadIpcContract: () => ipcRenderer.invoke('load-ipc-contract'),

  // Open settings window, optionally to a specific section
  openSettings: (section) => ipcRenderer.send('open-settings', section || null),

  // Clean up listeners when they are no longer needed (important!)
  removeListener: (channel) => ipcRenderer.removeAllListeners(channel),

  // Generic listener for specific channels from main process
  on: (channel, callback) => {
    const newCallback = (_, data) => {
      callback(data);
    };
    ipcRenderer.on(channel, newCallback);
    return () => ipcRenderer.removeListener(channel, newCallback);
  }
});

// Home launcher API (used by home.html when loaded in the main window)
contextBridge.exposeInMainWorld('homeAPI', {
  openLiveDictation: () => ipcRenderer.send('home:open-live-dictation'),
  openFileTranscribe: () => ipcRenderer.send('home:open-file-transcribe'),
  openSettings: () => ipcRenderer.send('home:open-settings'),
  getApiKeyStatus: () => ipcRenderer.invoke('apikey:status')
});

// File transcription API (used by filetranscribe.html when loaded in the main window)
contextBridge.exposeInMainWorld('fileTranscribeAPI', {
  pickFiles: () => ipcRenderer.invoke('file:pick'),
  transcribe: (opts) => ipcRenderer.invoke('file:transcribe', opts),
  exportText: (text, format, suggestedName) => ipcRenderer.invoke('file:export', { text, format, suggestedName }),
  copyText: (text) => clipboard.writeText(text || ''),
  getSettings: () => ipcRenderer.invoke('load-settings'),
  onProgress: (callback) => {
    const handler = (_event, data) => callback(data);
    ipcRenderer.on('file:transcribe-progress', handler);
    return () => ipcRenderer.removeListener('file:transcribe-progress', handler);
  },
  onResult: (callback) => {
    const handler = (_event, data) => callback(data);
    ipcRenderer.on('file:transcribe-result', handler);
    return () => ipcRenderer.removeListener('file:transcribe-result', handler);
  },

  // API key management
  getApiKeyStatus: () => ipcRenderer.invoke('apikey:status'),
  saveApiKey: (provider, value) => ipcRenderer.invoke('apikey:save', { provider, value }),
  deleteApiKey: (provider) => ipcRenderer.invoke('apikey:delete', { provider }),
  // Model management
  ensureModel: (modelId) => ipcRenderer.invoke('ensure-model', modelId)
});

// Navigation API (available on all pages loaded in the main window)
contextBridge.exposeInMainWorld('navAPI', {
  goHome: () => ipcRenderer.send('nav:go-home'),
  goLiveDictation: () => ipcRenderer.send('home:open-live-dictation'),
  goFileTranscribe: () => ipcRenderer.send('home:open-file-transcribe')
});

console.log('Preload script loaded.');
