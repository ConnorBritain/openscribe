const { contextBridge, ipcRenderer, clipboard } = require('electron');

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
  }
});
