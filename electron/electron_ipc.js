// electron_ipc.js
// Handles IPC handlers for renderer-main process communication

const { ipcMain } = require('electron');
const { setTrayIconByState, refreshTrayMenu } = require('./electron_tray');
const { store } = require('./electron_app_init'); // For accessing electron-store
const { getPythonShell, getActualAvailableLLMs } = require('./electron_python');
const historyService = require('./history_service');

function initializeIpcHandlers() {
  // Handle tray icon state updates from renderer
  ipcMain.on('set-tray-state', (_event, state) => {
    // Defensive logging for debugging
    console.log('[IPC] set-tray-state received:', state);
    setTrayIconByState(state);
  });

  // Handle stop dictation (process audio) command
  ipcMain.on('stop-dictation', (_event) => {
    console.log('[IPC] stop-dictation received');
    const pythonShell = getPythonShell();
    if (pythonShell && pythonShell.send) {
      pythonShell.send('STOP_DICTATION');
      console.log('[IPC] STOP_DICTATION command sent to Python backend');
    } else {
      console.error('[IPC] Python shell not available for STOP_DICTATION command');
    }
  });

  // Handle abort dictation (discard audio) command
  ipcMain.on('abort-dictation', (_event) => {
    console.log('[IPC] abort-dictation received');
    const pythonShell = getPythonShell();
    if (pythonShell && pythonShell.send) {
      pythonShell.send('ABORT_DICTATION');
      console.log('[IPC] ABORT_DICTATION command sent to Python backend');
    } else {
      console.error('[IPC] Python shell not available for ABORT_DICTATION command');
    }
  });

  ipcMain.on('set-wake-word-enabled', (_event, enabled) => {
    const enabledBool = !!enabled;
    console.log('[IPC] set-wake-word-enabled received:', enabledBool);
    store.set('wakeWordEnabled', enabledBool);
    refreshTrayMenu();

    try {
      const pythonShell = getPythonShell();
      if (pythonShell && pythonShell.send) {
        const configPayload = {
          wakeWords: store.get('wakeWords', { dictate: [] }),
          filterFillerWords: store.get('filterFillerWords', true),
          fillerWords: store.get('fillerWords', []),
          autoStopOnSilence: store.get('autoStopOnSilence', true),
          wakeWordEnabled: enabledBool
        };
        const savedAsrModel = store.get('selectedAsrModel');
        if (savedAsrModel) {
          configPayload.selectedAsrModel = savedAsrModel;
        }
        const msg = `CONFIG:${JSON.stringify(configPayload)}`;
        pythonShell.send(msg);
        console.log('[IPC] Wake word setting pushed to Python backend.');
      }
    } catch (e) {
      console.error('[IPC] Error pushing wake word toggle to Python backend:', e);
    }
  });

  // Handle re-paste text command (used by "Use this" button for background retranscription)
  ipcMain.on('repaste-text', (_event, text) => {
    console.log('[IPC] repaste-text received');
    const pythonShell = getPythonShell();
    if (pythonShell && pythonShell.send) {
      pythonShell.send(`REPASTE:${text}`);
    } else {
      console.error('[IPC] Python shell not available for REPASTE command');
    }
  });

  // Add other ipcMain.on handlers here if needed in the future

  // Handle settings saving
  ipcMain.on('save-settings', (_event, settings) => {
    console.log('[IPC] save-settings received:', settings);
    if (settings) {
      // Save wake words
      if (settings.wakeWords) {
        store.set('wakeWords', settings.wakeWords);
      }
      if (typeof settings.wakeWordEnabled === 'boolean') {
        store.set('wakeWordEnabled', settings.wakeWordEnabled);
        refreshTrayMenu();
      }
      // Save ASR model selection
      if (settings.selectedAsrModel) {
        store.set('selectedAsrModel', settings.selectedAsrModel);
      }
      if (typeof settings.filterFillerWords === 'boolean') {
        store.set('filterFillerWords', settings.filterFillerWords);
      }
      if (Array.isArray(settings.fillerWords)) {
        store.set('fillerWords', settings.fillerWords);
      }
      if (typeof settings.autoStopOnSilence === 'boolean') {
        store.set('autoStopOnSilence', settings.autoStopOnSilence);
      }
      if (settings.secondaryAsrModel !== undefined) {
        store.set('secondaryAsrModel', settings.secondaryAsrModel);
      }
      console.log('[IPC] Settings saved to store.');

      // Proactively push updated config to Python backend so model changes take effect immediately
      try {
        const pythonShell = getPythonShell();
        if (pythonShell && pythonShell.send) {
          const configPayload = {
            wakeWords: store.get('wakeWords', { dictate: [] }),
            filterFillerWords: store.get('filterFillerWords', true),
            fillerWords: store.get('fillerWords', []),
            autoStopOnSilence: store.get('autoStopOnSilence', true),
            wakeWordEnabled: store.get('wakeWordEnabled', true)
          };
          const savedAsrModel = store.get('selectedAsrModel');
          if (savedAsrModel) {
            configPayload.selectedAsrModel = savedAsrModel;
          }
          const savedSecondaryModel = store.get('secondaryAsrModel');
          if (savedSecondaryModel) {
            configPayload.secondaryAsrModel = savedSecondaryModel;
          }
          const msg = `CONFIG:${JSON.stringify(configPayload)}`;
          pythonShell.send(msg);
          console.log('[IPC] Pushed updated CONFIG to Python backend.');
        } else {
          console.warn('[IPC] Python shell not available to push updated CONFIG. It will apply on next launch.');
        }
      } catch (e) {
        console.error('[IPC] Error pushing updated CONFIG to Python backend:', e);
      }
    }
  });

  // Handle settings loading
  ipcMain.handle('load-settings', async () => {
    const settings = {
      wakeWords: store.get('wakeWords', { dictate: [] }),
      selectedAsrModel: store.get('selectedAsrModel', ''),
      filterFillerWords: store.get('filterFillerWords', true),
      fillerWords: store.get('fillerWords', []),
      autoStopOnSilence: store.get('autoStopOnSilence', true),
      wakeWordEnabled: store.get('wakeWordEnabled', true),
      secondaryAsrModel: store.get('secondaryAsrModel', null),
      availableModels: getActualAvailableLLMs() || []
    };
    console.log('[IPC] load-settings: returning', settings);
    return settings;
  });

  ipcMain.handle('ensure-model', async (_event, modelId) => {
    console.log('[IPC] ensure-model received:', modelId);
    const pythonShell = getPythonShell();
    if (!modelId) {
      return { success: false, error: 'Missing model identifier.' };
    }
    if (!pythonShell || !pythonShell.send) {
      console.error('[IPC] Python shell not available for ENSURE_MODEL command');
      return { success: false, error: 'Python backend not available.' };
    }

    return new Promise((resolve) => {
      const requestId = `ensure_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      let resolved = false;

      const cleanup = () => {
        pythonShell.removeListener('message', messageHandler);
      };

      const resolveOnce = (payload) => {
        if (!resolved) {
          resolved = true;
          cleanup();
          resolve(payload);
        }
      };

      const messageHandler = (message) => {
        if (typeof message !== 'string') {
          return;
        }
        if (message.startsWith(`MODEL_READY:${requestId}:`)) {
          const prefix = `MODEL_READY:${requestId}:`;
          const jsonPayload = message.substring(prefix.length);
          try {
            const parsed = JSON.parse(jsonPayload);
            resolveOnce(parsed);
          } catch (error) {
            resolveOnce({ success: false, error: `Malformed MODEL_READY payload: ${error}` });
          }
        } else if (message.startsWith(`MODEL_ERROR:${requestId}:`)) {
          const prefix = `MODEL_ERROR:${requestId}:`;
          const jsonPayload = message.substring(prefix.length);
          try {
            const parsed = JSON.parse(jsonPayload);
            resolveOnce(parsed);
          } catch (error) {
            resolveOnce({ success: false, error: `Malformed MODEL_ERROR payload: ${error}` });
          }
        }
      };

      pythonShell.on('message', messageHandler);
      pythonShell.send(`ENSURE_MODEL:${requestId}:${modelId}`);

      setTimeout(() => {
        resolveOnce({ success: false, error: 'Timed out while preparing model assets.' });
      }, 120000); // 2 minute timeout for large downloads
    });
  });

  ipcMain.handle('history:list', async () => {
    return historyService.getHistorySummary();
  });

  ipcMain.handle('history:entry', async (_event, entryId) => {
    return historyService.getHistoryEntry(entryId);
  });

  ipcMain.handle('history:delete', async (_event, entryId) => {
    try {
      return historyService.deleteHistoryEntry(entryId);
    } catch (error) {
      console.error('[IPC] history:delete failed:', error);
      return { success: false, error: error?.message || 'Failed to delete history entry.' };
    }
  });

  ipcMain.handle('history:retranscribe', async (_event, entryId, modelId) => {
    console.log(`[IPC] history:retranscribe received: ${entryId} -> ${modelId}`);
    try {
      const pythonShell = getPythonShell();
      if (!pythonShell || !pythonShell.send) {
        return { success: false, error: 'Python backend not available' };
      }

      return new Promise((resolve) => {
        const requestId = `retrans_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

        const responseHandler = (message) => {
          if (message.startsWith(`RETRANSCRIBE_RESULT:${requestId}:`)) {
            pythonShell.removeListener('message', responseHandler);
            try {
              const response = JSON.parse(message.split(`RETRANSCRIBE_RESULT:${requestId}:`)[1]);
              resolve(response);
            } catch (error) {
              console.error('[IPC] Error parsing re-transcribe response:', error);
              resolve({ success: false, error: 'Invalid response format' });
            }
          }
        };

        pythonShell.on('message', responseHandler);

        // Command format: RETRANSCRIBE_AUDIO:<requestId>:<entryId>:<modelId>
        pythonShell.send(`RETRANSCRIBE_AUDIO:${requestId}:${entryId}:${modelId}`);

        // Set longer timeout for model loading + transcription (5 minutes)
        setTimeout(() => {
          pythonShell.removeListener('message', responseHandler);
          resolve({ success: false, error: 'Re-transcription timed out' });
        }, 300000);
      });
    } catch (error) {
      console.error('[IPC] history:retranscribe error:', error);
      return { success: false, error: error.message };
    }
  });

  // Handle vocabulary API calls
  ipcMain.handle('vocabulary-api', async (_event, command, data = {}) => {
    console.log('[IPC] vocabulary-api received:', command, data);

    try {
      const pythonShell = getPythonShell();
      if (!pythonShell || !pythonShell.send) {
        console.error('[IPC] Python shell not available for vocabulary API');
        return { success: false, error: 'Python backend not available' };
      }

      // Send vocabulary command to Python backend
      return new Promise((resolve) => {
        const messageId = `vocab_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

        // Set up one-time listener for the response
        const responseHandler = (message) => {
          if (message.startsWith(`VOCAB_RESPONSE:${messageId}:`)) {
            pythonShell.removeListener('message', responseHandler);
            try {
              const response = JSON.parse(message.split(`VOCAB_RESPONSE:${messageId}:`)[1]);
              resolve(response);
            } catch (error) {
              console.error('[IPC] Error parsing vocabulary response:', error);
              resolve({ success: false, error: 'Invalid response format' });
            }
          }
        };

        pythonShell.on('message', responseHandler);

        // Send the command with message ID
        const vocabularyMessage = `VOCABULARY_API:${messageId}:${JSON.stringify({ command, data })}`;
        pythonShell.send(vocabularyMessage);

        // Set timeout for response
        setTimeout(() => {
          pythonShell.removeListener('message', responseHandler);
          resolve({ success: false, error: 'Vocabulary API timeout' });
        }, 5000);
      });

    } catch (error) {
      console.error('[IPC] Error in vocabulary API:', error);
      return { success: false, error: error.message };
    }
  });

  console.log('[IPC] IPC Handlers Initialized');
}

module.exports = { initializeIpcHandlers };
