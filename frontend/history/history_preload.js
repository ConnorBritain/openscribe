const { contextBridge, ipcRenderer, clipboard } = require('electron');

contextBridge.exposeInMainWorld('historyAPI', {
  getList: () => ipcRenderer.invoke('history:list'),
  getEntry: (entryId) => ipcRenderer.invoke('history:entry', entryId),
  deleteEntry: (entryId) => ipcRenderer.invoke('history:delete', entryId),
  learnCorrection: (payload) => ipcRenderer.invoke('vocabulary-api', 'learn_correction', payload),
  copyText: (text) => clipboard.writeText(text || ''),
  retranscribe: (entryId, modelId) => ipcRenderer.invoke('history:retranscribe', entryId, modelId),
  getAsrModels: () => ipcRenderer.invoke('load-settings').then(s => s.availableModels || [])
});
