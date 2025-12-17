// renderer_state.js
// Handles UI state management and status indicator updates

import { statusDot, stopButton, cancelButton, modeIndicator, processingIndicator, amplitudes, wakeWordToggleButton } from './renderer_ui.js';
import { conflictNotificationManager } from './renderer_conflict_ui.js';

// Exported variable for the audio visualizer and other potential consumers
export let currentAudioState = 'inactive';
export let isAlwaysOnTop = false;

const STATUS_VISUALS = {
  green: { color: '#34c759', shadow: '#34c759', visualizer: 'dictation' },
  blue: { color: '#007aff', shadow: '#007aff', visualizer: 'listening' },
  orange: { color: '#ff9500', shadow: '#ff9500', visualizer: 'inactive' },
  red: { color: '#ff3b30', shadow: '#ff3b30', visualizer: 'inactive' },
  grey: { color: '#8e8e93', shadow: null, visualizer: 'inactive' },
  gray: { color: '#8e8e93', shadow: null, visualizer: 'inactive' }
};

function resolveStatusDot() {
  return document.getElementById('status-dot') || statusDot;
}

function setVisualizerState(nextState) {
  const validStates = ['dictation', 'listening'];
  const desired = validStates.includes(nextState) ? nextState : 'inactive';
  const previous = currentAudioState;
  currentAudioState = desired;

  if (!amplitudes) {
    return;
  }

  if (desired === 'inactive' || (previous === 'dictation' && desired !== 'dictation')) {
    amplitudes.fill(0);
  }
}

function applyStatusDotVisuals(colorKey, overrideVisualizerState) {
  const dot = resolveStatusDot();
  if (!dot) {
    if (overrideVisualizerState) {
      setVisualizerState(overrideVisualizerState);
    }
    return;
  }

  const normalizedKey = colorKey ? colorKey.toLowerCase() : '';
  const visuals = STATUS_VISUALS[normalizedKey];

  if (visuals) {
    dot.style.backgroundColor = visuals.color;
    dot.style.boxShadow = visuals.shadow ? `0 0 5px ${visuals.shadow}` : 'none';
  } else if (typeof colorKey === 'string' && colorKey) {
    console.warn('[RendererState] Unknown status color:', colorKey);
  }

  const targetVisualizerState = overrideVisualizerState || (visuals ? visuals.visualizer : undefined);
  if (targetVisualizerState) {
    setVisualizerState(targetVisualizerState);
  }
}

// Module-level state, managed by updateStatusIndicator
let internalState = {
  programActive: false,
  audioState: 'inactive',
  isDictating: false,
  currentMode: null,
  microphoneError: null,
  lastConflictCheck: 0,
  wakeWordEnabled: true
};

function updateWakeWordToggle(enabled, programActive) {
  if (!wakeWordToggleButton) {
    return;
  }
  const isEnabled = enabled !== false;
  wakeWordToggleButton.dataset.enabled = isEnabled ? 'true' : 'false';
  wakeWordToggleButton.classList.toggle('wakeword-off', !isEnabled);
  wakeWordToggleButton.setAttribute('aria-pressed', isEnabled ? 'true' : 'false');
  wakeWordToggleButton.textContent = isEnabled ? 'Wake Word On' : 'Wake Word Off';
  // Keep interactive even if mic unavailable so the preference can be set ahead of time
  wakeWordToggleButton.disabled = false;
  if (!programActive) {
    wakeWordToggleButton.title = 'Wake words paused until microphone is available';
  } else {
    wakeWordToggleButton.title = 'Toggle listening for wake words';
  }
}

export function updateStatusIndicator(newState) {
  internalState.programActive = typeof newState.programActive === 'boolean' ? newState.programActive : internalState.programActive;
  internalState.audioState = newState.audioState || internalState.audioState;
  internalState.isDictating = typeof newState.isDictating === 'boolean' ? newState.isDictating : internalState.isDictating;
  internalState.currentMode = newState.currentMode !== undefined ? newState.currentMode : internalState.currentMode;
  internalState.microphoneError = newState.microphoneError || null;
  internalState.wakeWordEnabled = typeof newState.wakeWordEnabled === 'boolean' ? newState.wakeWordEnabled : internalState.wakeWordEnabled;

  updateWakeWordToggle(internalState.wakeWordEnabled, internalState.programActive);

  console.log('[RendererState] updateStatusIndicator called with:', newState);
  console.log('[RendererState] Internal state after update:', internalState);

  const dot = resolveStatusDot();
  if (!dot) {
    return;
  }

  if (!internalState.programActive) {
    if (internalState.microphoneError) {
      applyStatusDotVisuals('red', 'inactive');
      dot.title = `Microphone Error: ${internalState.microphoneError}`;
      dot.style.animation = 'pulse-error 2s infinite';
    } else {
      applyStatusDotVisuals('grey', 'inactive');
      dot.title = '';
      dot.style.animation = '';
    }

    if (stopButton) stopButton.disabled = true;
    if (cancelButton) cancelButton.disabled = true;
    setVisualizerState('inactive');
    if (modeIndicator) modeIndicator.style.display = 'none';
    if (processingIndicator) processingIndicator.style.display = 'none';
    updateWakeWordToggle(internalState.wakeWordEnabled, internalState.programActive);
    return;
  }

  dot.title = '';
  dot.style.animation = '';

  let effectiveVisibleAudioState = internalState.audioState;
  if (internalState.isDictating) {
    effectiveVisibleAudioState = 'dictation';
  }

  if (modeIndicator) modeIndicator.style.display = 'none';
  if (processingIndicator) processingIndicator.style.display = 'none';

  switch (effectiveVisibleAudioState) {
  case 'activation':
  case 'preparing':
    if (internalState.wakeWordEnabled) {
      applyStatusDotVisuals('blue', 'listening');
    } else {
      applyStatusDotVisuals('grey', 'inactive');
    }
    if (stopButton) stopButton.disabled = true;
    if (cancelButton) cancelButton.disabled = true;
    break;
  case 'dictation':
    applyStatusDotVisuals('green', 'dictation');
    if (stopButton) stopButton.disabled = false;
    if (cancelButton) cancelButton.disabled = false;
    if (modeIndicator && internalState.currentMode === 'dictate') {
      modeIndicator.textContent = 'Note';
      modeIndicator.style.display = 'inline-block';
    }
    break;
  case 'processing':
    applyStatusDotVisuals('orange', 'inactive');
    if (stopButton) stopButton.disabled = true;
    if (cancelButton) cancelButton.disabled = true;
    if (processingIndicator) processingIndicator.style.display = 'inline-block';
    break;
  case 'inactive':
  default:
    applyStatusDotVisuals('grey', 'inactive');
    if (stopButton) stopButton.disabled = true;
    if (cancelButton) cancelButton.disabled = true;
    if (modeIndicator) modeIndicator.style.display = 'none';
    if (processingIndicator) processingIndicator.style.display = 'none';
    break;
  }

  updateWakeWordToggle(internalState.wakeWordEnabled, internalState.programActive);
}

export function initializeStatusIndicator() {
  console.log('[RendererState] Initializing status indicator to inactive state');
  const dot = resolveStatusDot();
  console.log('[RendererState] statusDot element:', dot);

  if (dot) {
    dot.style.backgroundColor = '#8e8e93';
    dot.style.boxShadow = 'none';
    console.log('[RendererState] Successfully set status dot to grey');
  } else {
    console.warn('[RendererState] statusDot element not found during initialization');
  }

  updateStatusIndicator({
    programActive: false,
    audioState: 'inactive',
    isDictating: false,
    currentMode: null,
    microphoneError: null
  });
}

export function getMicrophoneError() {
  return internalState.microphoneError;
}

export function hasMicrophoneError() {
  return !!internalState.microphoneError;
}

export function handleStatusMessage(statusText, color) {
  if (color === 'red' && (statusText.toLowerCase().includes('microphone') || statusText.toLowerCase().includes('audio'))) {
    internalState.microphoneError = statusText;
  } else if (color === 'green' || color === 'blue') {
    internalState.microphoneError = null;
  }

  const definitiveConflictPhrases = [
    'microphone conflict detected',
    'detected active conflict',
    'conflicting application detected',
    'microphone access blocked',
    'another application is using the microphone',
    'audio input conflict'
  ];

  const isDefinitiveConflict = definitiveConflictPhrases.some((phrase) =>
    statusText.toLowerCase().includes(phrase.toLowerCase())
  );

  const isBrowserConflictMessage = statusText.toLowerCase().includes('microphone conflict detected') &&
    (statusText.toLowerCase().includes('safari') ||
     statusText.toLowerCase().includes('chrome') ||
     statusText.toLowerCase().includes('browser'));

  const isSuggestionMessage = statusText.includes('💡') ||
    statusText.toLowerCase().includes('note:') ||
    statusText.toLowerCase().includes('tip:') ||
    (statusText.toLowerCase().includes('close') && statusText.toLowerCase().includes('tab')) ||
    (statusText.toLowerCase().includes('disable') && statusText.toLowerCase().includes('access'));

  if ((isDefinitiveConflict || isBrowserConflictMessage) && !isSuggestionMessage) {
    const currentTime = Date.now();
    if (currentTime - internalState.lastConflictCheck > 5000) {
      internalState.lastConflictCheck = currentTime;

      let conflictDetails = statusText;
      if (statusText.toLowerCase().includes('safari') || statusText.toLowerCase().includes('chrome')) {
        conflictDetails = 'Safari or Chrome is actively using the microphone for dictation';
      } else if (statusText.toLowerCase().includes('browser')) {
        conflictDetails = 'Web browser is actively using the microphone for dictation';
      } else if (statusText.toLowerCase().includes('another application')) {
        conflictDetails = 'Another application is using the microphone';
      }

      conflictNotificationManager.showConflictBanner(conflictDetails);
    }
  }

  if (isSuggestionMessage) {
    console.log('Conflict suggestion received:', statusText);
  }

  const normalizedColor = typeof color === 'string' ? color.toLowerCase() : '';
  // Avoid overriding app state for neutral grey messages (e.g., config updates)
  if (normalizedColor === 'grey' || normalizedColor === 'gray') {
    return;
  }

  if (normalizedColor) {
    let overrideState;
    if (normalizedColor === 'green') {
      overrideState = 'dictation';
    } else if (normalizedColor === 'blue') {
      overrideState = 'listening';
    } else {
      overrideState = 'inactive';
    }
    applyStatusDotVisuals(normalizedColor, overrideState);
  }
}

export function hideConflictNotification() {
  conflictNotificationManager.hideConflictBanner();
}

export function isConflictNotificationVisible() {
  return conflictNotificationManager.isConflictVisible();
}
