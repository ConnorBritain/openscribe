// renderer_controls.js
// Handles button clicks and keyboard shortcuts for stop/cancel functionality

import {
  stopButton,
  cancelButton,
  alwaysOnTopButton,
  wakeWordToggleButton,
  pillCancelButton
} from './renderer_ui.js';
import { logMessage } from './renderer_utils.js';
import { updateStatusIndicator } from './renderer_state.js';

export function initializeControls() {
  // Stop button click handler
  if (stopButton) {
    stopButton.addEventListener('click', () => {
      logMessage('Stop button clicked', 'controls');
      if (window.electronAPI && window.electronAPI.stopDictation) {
        window.electronAPI.stopDictation();
      } else {
        logMessage('electronAPI.stopDictation not available', 'error');
      }
    });
  }

  // Cancel button click handler
  if (cancelButton) {
    cancelButton.addEventListener('click', () => {
      logMessage('Cancel button clicked', 'controls');
      if (window.electronAPI && window.electronAPI.abortDictation) {
        window.electronAPI.abortDictation();
      } else {
        logMessage('electronAPI.abortDictation not available', 'error');
      }
    });
  }

  // Compact pill cancel button (Handy-style) mirrors main cancel behavior
  if (pillCancelButton) {
    pillCancelButton.addEventListener('click', () => {
      logMessage('Pill cancel button clicked', 'controls');
      if (window.electronAPI && window.electronAPI.abortDictation) {
        window.electronAPI.abortDictation();
      } else {
        logMessage('electronAPI.abortDictation not available', 'error');
      }
    });
  }

  // Always on top button click handler
  if (alwaysOnTopButton) {
    alwaysOnTopButton.addEventListener('click', () => {
      logMessage('Always on top button clicked', 'controls');
      if (window.electronAPI && window.electronAPI.toggleAlwaysOnTop) {
        window.electronAPI.toggleAlwaysOnTop();
      } else {
        logMessage('electronAPI.toggleAlwaysOnTop not available', 'error');
      }
    });
  }

  if (wakeWordToggleButton) {
    wakeWordToggleButton.addEventListener('click', () => {
      const currentlyEnabled = wakeWordToggleButton.dataset.enabled !== 'false';
      const nextEnabled = !currentlyEnabled;
      logMessage(`Wake word toggle clicked -> ${nextEnabled ? 'on' : 'off'}`, 'controls');
      if (window.electronAPI && window.electronAPI.setWakeWordEnabled) {
        window.electronAPI.setWakeWordEnabled(nextEnabled);
        // Optimistically update the UI for responsiveness; authoritative state comes from backend STATE message
        const provisionalState = {
          audioState: 'activation',
          programActive: true,
          isDictating: false,
          currentMode: null,
          wakeWordEnabled: nextEnabled
        };
        updateStatusIndicator(provisionalState);
      } else {
        logMessage('electronAPI.setWakeWordEnabled not available', 'error');
      }
    });
  }

  // Keyboard event handlers
  document.addEventListener('keydown', (event) => {
    // Space key for stop (during dictation)
    if (event.code === 'Space') {
      event.preventDefault();
      logMessage('Space pressed - stopping dictation', 'controls');
      if (window.electronAPI && window.electronAPI.stopDictation) {
        window.electronAPI.stopDictation();
      }
    }

    // Escape key for cancel
    if (event.code === 'Escape') {
      event.preventDefault();
      logMessage('Escape pressed - canceling dictation', 'controls');
      if (window.electronAPI && window.electronAPI.abortDictation) {
        window.electronAPI.abortDictation();
      }
    }
  });

  logMessage('Control handlers initialized', 'controls');
}
