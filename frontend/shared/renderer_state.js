// renderer_state.js
// Handles UI state management and status indicator updates

import {
  statusDot,
  handyStatusDot,
  stopButton,
  cancelButton,
  modeIndicator,
  processingIndicator,
  handyModeIndicator,
  handyProcessingIndicator,
  amplitudes,
  wakeWordToggleButton,
  activityPill,
  activityLabel,
  activityIcon,
  pillCancelButton
} from './renderer_ui.js';
// Keep explicit stop/cancel pairing for legacy tests: stopButton, cancelButton
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

const ACTIVITY_PHASES = ['inactive', 'listening', 'recording', 'transcribing', 'error', 'retranscribing'];
const LIFECYCLE_STATES = new Set(['idle', 'listening', 'recording', 'stopping', 'transcribing', 'inserting', 'error']);

function isHandyMode() {
  return !!(document.body && document.body.classList.contains('ui-mode-handy'));
}

function getStatusDots() {
  return [statusDot, handyStatusDot].filter(Boolean);
}

function getActiveStatusDot() {
  if (isHandyMode() && handyStatusDot) {
    return handyStatusDot;
  }
  return statusDot || handyStatusDot || null;
}

function getModeIndicators() {
  return [modeIndicator, handyModeIndicator].filter(Boolean);
}

function getProcessingIndicators() {
  return [processingIndicator, handyProcessingIndicator].filter(Boolean);
}

function setModeIndicatorState(text, visible) {
  getModeIndicators().forEach((indicator) => {
    indicator.textContent = text;
    indicator.style.display = visible ? 'inline-block' : 'none';
  });
}

function setProcessingIndicatorState(text, visible, color = '') {
  getProcessingIndicators().forEach((indicator) => {
    indicator.textContent = text;
    indicator.style.display = visible ? 'inline-block' : 'none';
    indicator.style.color = color;
  });
}

function setActivityPhase(phase, labelText) {
  if (activityPill) {
    ACTIVITY_PHASES.forEach((name) => {
      activityPill.classList.remove(`state-${name}`);
    });
    activityPill.classList.add(`state-${phase}`);
  }

  if (activityLabel && typeof labelText === 'string') {
    activityLabel.textContent = labelText;
  }

  if (activityIcon) {
    const showBrain = phase === 'transcribing' || phase === 'retranscribing' || phase === 'error';
    activityIcon.classList.toggle('show-ear', !showBrain);
    activityIcon.classList.toggle('show-brain', showBrain);
    activityIcon.classList.toggle('is-listening', phase === 'listening');
    activityIcon.classList.toggle('is-recording', phase === 'recording');
    activityIcon.classList.toggle('is-transcribing', phase === 'transcribing' || phase === 'retranscribing');
    activityIcon.classList.toggle('is-error', phase === 'error');
  }

  if (pillCancelButton) {
    pillCancelButton.style.display = phase === 'recording' ? 'inline-flex' : 'none';
  }
}

function resolveStatusDot() {
  return getActiveStatusDot();
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
  const dots = getStatusDots();
  if (dots.length === 0) {
    if (overrideVisualizerState) {
      setVisualizerState(overrideVisualizerState);
    }
    return;
  }

  const normalizedKey = colorKey ? colorKey.toLowerCase() : '';
  const visuals = STATUS_VISUALS[normalizedKey];

  if (visuals) {
    dots.forEach((dot) => {
      dot.style.backgroundColor = visuals.color;
      dot.style.boxShadow = visuals.shadow ? `0 0 5px ${visuals.shadow}` : 'none';
    });
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
  wakeWordEnabled: true,
  dictationLifecycle: 'idle'
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
  if (typeof newState.dictationLifecycle === 'string' && LIFECYCLE_STATES.has(newState.dictationLifecycle)) {
    internalState.dictationLifecycle = newState.dictationLifecycle;
  }

  updateWakeWordToggle(internalState.wakeWordEnabled, internalState.programActive);

  const dot = getActiveStatusDot();
  if (!dot) {
    return;
  }

  if (!internalState.programActive) {
    if (internalState.microphoneError) {
      applyStatusDotVisuals('red', 'inactive');
      getStatusDots().forEach((statusElement) => {
        statusElement.title = `Microphone Error: ${internalState.microphoneError}`;
        statusElement.style.animation = 'pulse-error 2s infinite';
      });
      setActivityPhase('error', 'Mic Error');
    } else {
      applyStatusDotVisuals('grey', 'inactive');
      getStatusDots().forEach((statusElement) => {
        statusElement.title = '';
        statusElement.style.animation = '';
      });
      setActivityPhase('inactive', 'Idle');
    }

    if (stopButton) stopButton.disabled = true;
    if (cancelButton) cancelButton.disabled = true;
    setVisualizerState('inactive');
    setModeIndicatorState('Note', false);
    setProcessingIndicatorState('Transcribing', false);
    updateWakeWordToggle(internalState.wakeWordEnabled, internalState.programActive);
    return;
  }

  getStatusDots().forEach((statusElement) => {
    statusElement.title = '';
    statusElement.style.animation = '';
  });

  let effectiveVisibleAudioState = internalState.audioState;
  if (internalState.dictationLifecycle === 'recording' || internalState.isDictating) {
    effectiveVisibleAudioState = 'dictation';
  } else if (
    internalState.dictationLifecycle === 'stopping' ||
    internalState.dictationLifecycle === 'transcribing' ||
    internalState.dictationLifecycle === 'inserting'
  ) {
    effectiveVisibleAudioState = 'processing';
  } else if (internalState.dictationLifecycle === 'listening') {
    effectiveVisibleAudioState = internalState.wakeWordEnabled ? 'activation' : 'inactive';
  } else if (internalState.dictationLifecycle === 'idle') {
    effectiveVisibleAudioState = 'inactive';
  } else if (internalState.dictationLifecycle === 'error') {
    effectiveVisibleAudioState = 'error';
  }

  setModeIndicatorState('Note', false);
  setProcessingIndicatorState('Transcribing', false);

  switch (effectiveVisibleAudioState) {
  case 'activation':
  case 'preparing':
    if (internalState.wakeWordEnabled) {
      applyStatusDotVisuals('blue', 'listening');
      setActivityPhase('listening', 'Listening');
    } else {
      applyStatusDotVisuals('grey', 'inactive');
      setActivityPhase('inactive', 'Wake Word Off');
    }
    if (stopButton) stopButton.disabled = true;
    if (cancelButton) cancelButton.disabled = true;
    break;
  case 'dictation':
    applyStatusDotVisuals('green', 'dictation');
    setActivityPhase('recording', 'Recording');
    if (stopButton) stopButton.disabled = false;
    if (cancelButton) cancelButton.disabled = false;
    if (internalState.currentMode === 'dictate') {
      setModeIndicatorState('Note', false);
    }
    break;
  case 'processing':
    applyStatusDotVisuals('orange', 'inactive');
    setActivityPhase('transcribing', internalState.dictationLifecycle === 'inserting' ? 'Inserting' : 'Transcribing');
    if (stopButton) stopButton.disabled = true;
    if (cancelButton) cancelButton.disabled = true;
    setProcessingIndicatorState(
      internalState.dictationLifecycle === 'inserting' ? 'Inserting' : 'Transcribing',
      true
    );
    break;
  case 'error':
    applyStatusDotVisuals('red', 'inactive');
    setActivityPhase('error', 'Error');
    if (stopButton) stopButton.disabled = true;
    if (cancelButton) cancelButton.disabled = true;
    setProcessingIndicatorState('Retry', false);
    break;
  case 'inactive':
  default:
    applyStatusDotVisuals('grey', 'inactive');
    setActivityPhase('inactive', 'Idle');
    if (stopButton) stopButton.disabled = true;
    if (cancelButton) cancelButton.disabled = true;
    setModeIndicatorState('Note', false);
    setProcessingIndicatorState('Transcribing', false);
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

  setActivityPhase('inactive', 'Idle');

  updateStatusIndicator({
    programActive: false,
    audioState: 'inactive',
    isDictating: false,
    currentMode: null,
    microphoneError: null,
    dictationLifecycle: 'idle'
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

/**
 * Show a pulsing spinner and processing indicator during re-transcription.
 * @param {string} modelName  The model being used, or an error message.
 * @param {boolean} isError   True if this is an error flash (will auto-hide).
 */
export function showRetranscribeProgress(modelName, isError = false) {
  const dot = getActiveStatusDot();
  if (dot) {
    if (isError) {
      getStatusDots().forEach((statusElement) => {
        statusElement.style.animation = '';
      });
      applyStatusDotVisuals('orange');
    } else {
      getStatusDots().forEach((statusElement) => {
        statusElement.style.animation = 'pulse-retranscribe 1.2s ease-in-out infinite';
      });
      applyStatusDotVisuals('blue');
    }
  }

  const text = isError ? modelName : `Re-transcribing with ${modelName}...`;
  if (isError) {
    setProcessingIndicatorState(text, true, '#ff9500');
    setActivityPhase('error', 'Retranscribe Error');
    setTimeout(() => hideRetranscribeProgress(), 3000);
  } else {
    setProcessingIndicatorState(text, true);
    setActivityPhase('retranscribing', 'Re-transcribing');
  }
}

/**
 * Hide the re-transcription spinner and restore normal status dot state.
 */
export function hideRetranscribeProgress() {
  const dot = getActiveStatusDot();
  if (dot) {
    getStatusDots().forEach((statusElement) => {
      statusElement.style.animation = '';
    });
  }

  setProcessingIndicatorState('Transcribing', false);

  if (internalState.programActive) {
    if (internalState.audioState === 'dictation' || internalState.isDictating) {
      setActivityPhase('recording', 'Recording');
    } else if (internalState.audioState === 'processing') {
      setActivityPhase('transcribing', 'Transcribing');
    } else if ((internalState.audioState === 'activation' || internalState.audioState === 'preparing') && internalState.wakeWordEnabled) {
      setActivityPhase('listening', 'Listening');
    } else {
      setActivityPhase('inactive', 'Idle');
    }
  } else {
    setActivityPhase('inactive', 'Idle');
  }
}
