// renderer_ipc.js
// Handles IPC communication with Electron main and Python backend

import { logMessage } from './renderer_utils.js';
import { updateStatusIndicator, handleStatusMessage, showRetranscribeProgress, hideRetranscribeProgress } from './renderer_state.js';
import { amplitudes } from './renderer_ui.js';
import {
  beginTranscriptSession,
  updateActiveTranscriptStatus,
  finalizeActiveTranscript,
  setTranscriptHeightCallback,
  setLastHistoryEntry,
  handleQuickRetranscribeResult,
  setRetranscribingState
} from './renderer_transcript_log.js';

const MIN_WINDOW_HEIGHT = 124;
const EXPANDED_WINDOW_HEIGHT = 320;

let lastAudioState = 'inactive';
let lastIsDictating = false;
let isResponseCollapsed = false;

function hasTranscriptEntries() {
  const stream = document.getElementById('transcript-stream');
  return !!(stream && stream.querySelector('.transcript-entry'));
}

function processDictationState(rawState) {
  if (!rawState) {
    return;
  }

  const audioState = rawState.audioState || (rawState.isDictating ? 'dictation' : 'inactive');
  const isDictating = !!rawState.isDictating;
  const normalizedState = {
    programActive: typeof rawState.programActive === 'boolean' ? rawState.programActive : true,
    audioState,
    isDictating,
    currentMode: rawState.currentMode !== undefined ? rawState.currentMode : null,
    wakeWordEnabled: rawState.wakeWordEnabled !== false
  };

  console.log('[RendererIPC] Dictation state update:', normalizedState);

  updateStatusIndicator(normalizedState);

  if (isDictating && !lastIsDictating) {
    beginTranscriptSession();
    adjustWindowHeight(false, { forceState: 'collapsed' });
  } else if (!isDictating && lastIsDictating) {
    adjustWindowHeight(false, { forceState: 'expanded' });
  }

  if (isDictating) {
    updateActiveTranscriptStatus('recording');
    adjustWindowHeight(false, { forceState: 'collapsed' });
  } else if (audioState === 'processing') {
    updateActiveTranscriptStatus('processing');
    adjustWindowHeight(false, { forceState: 'expanded' });
  } else if (audioState === 'activation' || audioState === 'preparing') {
    updateActiveTranscriptStatus('listening');
    if (!isDictating) {
      const hasEntries = hasTranscriptEntries();
      adjustWindowHeight(hasEntries, { forceState: hasEntries ? 'expanded' : 'collapsed' });
    }
  }

  const enteredActivation = (audioState === 'activation' || audioState === 'preparing') &&
    lastAudioState !== audioState;
  const enteredProcessing = audioState === 'processing' && lastAudioState !== 'processing';
  const becameInactive = audioState === 'inactive' && lastAudioState !== 'inactive';

  if (enteredActivation && !isDictating) {
    const hasEntries = hasTranscriptEntries();
    adjustWindowHeight(hasEntries, { forceState: hasEntries ? 'expanded' : 'collapsed' });
  }

  if (enteredProcessing && !isDictating) {
    adjustWindowHeight(false, { forceState: 'expanded' });
  }

  if (becameInactive) {
    const hasEntries = hasTranscriptEntries();
    adjustWindowHeight(hasEntries, hasEntries ? { forceState: 'expanded' } : { forceState: 'collapsed' });
  }

  lastIsDictating = isDictating;
  lastAudioState = audioState;
}

function applyTranscriptVisibility(collapsed) {
  const responseArea = document.getElementById('response-area');
  const appContainer = document.getElementById('app-container');
  if (!responseArea) {
    return;
  }

  isResponseCollapsed = collapsed;
  responseArea.dataset.collapsed = collapsed ? 'true' : 'false';
  responseArea.style.display = collapsed ? 'none' : 'flex';

  if (appContainer) {
    appContainer.classList.toggle('is-transcript-collapsed', collapsed);
  }
}

function setResponseText(text) {
  const cleaned = typeof text === 'string' ? text.trim() : '';
  finalizeActiveTranscript(cleaned);
  adjustWindowHeight(cleaned.length > 0, {
    forceState: 'expanded'
  });
}

function adjustWindowHeight(hasTranscript = false, options = {}) {
  const { forceState = null } = options;

  if (!window.electronAPI || typeof window.electronAPI.resizeWindow !== 'function') {
    return;
  }

  const responseArea = document.getElementById('response-area');
  if (!responseArea) {
    return;
  }

  if (forceState === 'collapsed') {
    applyTranscriptVisibility(true);
  } else if (forceState === 'expanded') {
    applyTranscriptVisibility(false);
  }

  const isCollapsed = responseArea.dataset.collapsed === 'true';

  const transcriptStream = document.getElementById('transcript-stream');
  const hasVisibleEntries = !isCollapsed &&
    !!(transcriptStream && transcriptStream.querySelector('.transcript-entry'));

  const responseHeight = isCollapsed ? 0 : responseArea.scrollHeight;
  const headerHeight = (document.getElementById('waveform-area')?.offsetHeight || 0)
    + (document.getElementById('control-bar')?.offsetHeight || 0)
    + 20;

  const effectiveHasTranscript = !isCollapsed && (hasTranscript || hasVisibleEntries);

  const desiredHeight = effectiveHasTranscript
    ? Math.max(EXPANDED_WINDOW_HEIGHT, responseHeight + headerHeight)
    : Math.max(MIN_WINDOW_HEIGHT, headerHeight);
  const currentHeight = window.innerHeight || 0;

  if (Math.abs(desiredHeight - currentHeight) > 8) {
    window.electronAPI.resizeWindow({ height: Math.round(desiredHeight) });
  }
}

export function registerIPCHandlers() {
  setTranscriptHeightCallback(adjustWindowHeight);
  applyTranscriptVisibility(false);

  if (window.electronAPI && typeof window.electronAPI.on === 'function') {
    window.electronAPI.on('ui-update', (payload) => {
      if (payload && payload.type === 'dictation_status_update') {
        processDictationState(payload);
      }
    });
  }

  if (window.electronAPI && window.electronAPI.handleFromPython) {
    window.electronAPI.handleFromPython((message) => {
      if (!message.startsWith('AUDIO_AMP:')) {
        console.log('[IPC_FROM_PYTHON_RAW]', message);
        logMessage(message, 'py');
      }

      if (message.startsWith('STATUS:')) {
        const statusPayload = message.substring(7);
        const firstColon = statusPayload.indexOf(':');
        if (firstColon !== -1) {
          const color = statusPayload.substring(0, firstColon);
          const text = statusPayload.substring(firstColon + 1);
          handleStatusMessage(text, color);
        } else {
          handleStatusMessage(statusPayload, 'grey');
        }
      } else if (message.startsWith('FINAL_TRANSCRIPT:')) {
        const transcriptText = message.substring(17);
        setResponseText(transcriptText);
      } else if (message.startsWith('STATE:')) {
        try {
          const stateData = JSON.parse(message.substring(6));
          processDictationState(stateData);
        } catch (error) {
          logMessage(`Error parsing STATE JSON: ${error}`, 'error');
        }
      } else if (message.startsWith('AUDIO_AMP:')) {
        const amplitudeValue = parseInt(message.split(':')[1], 10);
        if (!Number.isNaN(amplitudeValue)) {
          amplitudes.push(amplitudeValue);
          if (amplitudes.length > 100) {
            amplitudes.shift();
          }
        }
      } else if (message.startsWith('HISTORY_ENTRY:')) {
        try {
          const entryData = JSON.parse(message.substring(14));
          setLastHistoryEntry(entryData);
        } catch (error) {
          logMessage(`Error parsing HISTORY_ENTRY JSON: ${error}`, 'error');
        }
      } else if (message.startsWith('RETRANSCRIBE_START:')) {
        const payload = message.substring(19);
        if (payload.startsWith('error:')) {
          showRetranscribeProgress(payload.substring(6), true);
        } else {
          showRetranscribeProgress(payload, false);
          setRetranscribingState(true);
        }
      } else if (message.startsWith('RETRANSCRIBE_END:')) {
        hideRetranscribeProgress();
        setRetranscribingState(false);
      } else if (message.startsWith('RETRANSCRIBE_QUICK_RESULT:')) {
        try {
          const resultData = JSON.parse(message.substring(26));
          handleQuickRetranscribeResult(resultData);
        } catch (error) {
          logMessage(`Error parsing RETRANSCRIBE_QUICK_RESULT JSON: ${error}`, 'error');
        }
      } else if (message.startsWith('HOTKEYS:')) {
        logMessage(`Received Hotkeys: ${message.substring(8)}`);
      } else if (message === 'BACKEND_READY') {
        logMessage('Python backend is ready.');
      } else if (message === 'SHUTDOWN_SIGNAL') {
        logMessage('Python backend is shutting down.');
        updateStatusIndicator({ audioState: 'inactive', programActive: false });
      }
    });
  }

  if (window.electronAPI && window.electronAPI.handlePythonStderr) {
    window.electronAPI.handlePythonStderr((errorMessage) => {
      logMessage(errorMessage, 'error');
      console.log('Python Stderr received in renderer:', errorMessage);
      if (errorMessage.toLowerCase().includes('error')) {
        const statusDot = document.getElementById('status-dot');
        if (statusDot) {
          statusDot.style.backgroundColor = '#ff3b30';
          statusDot.style.boxShadow = '0 0 5px #ff3b30';
        }
      }
    });
  }
}
