const { contextBridge, ipcRenderer, clipboard } = require('electron');

contextBridge.exposeInMainWorld('historyAPI', {
  getList: () => ipcRenderer.invoke('history:list'),
  getEntry: (entryId) => ipcRenderer.invoke('history:entry', entryId),
  deleteEntry: (entryId) => ipcRenderer.invoke('history:delete', entryId),
  copyText: (text) => clipboard.writeText(text || ''),
  retranscribe: (entryId, modelId) => ipcRenderer.invoke('history:retranscribe', entryId, modelId),
  getAsrModels: () => ipcRenderer.invoke('load-settings').then(s => s.availableModels || [])
});
