// renderer_ipc.js
// Handles IPC communication with Electron main and Python backend.

import { logMessage } from './renderer_utils.js';
import { updateStatusIndicator, handleStatusMessage, showRetranscribeProgress, hideRetranscribeProgress } from './renderer_state.js';
import { amplitudes, handyLevels } from './renderer_ui.js';
import {
  beginTranscriptSession,
  updateActiveTranscriptStatus,
  finalizeActiveTranscript,
  setTranscriptHeightCallback,
  setLastHistoryEntry,
  handleQuickRetranscribeResult,
  setRetranscribingState
} from './renderer_transcript_log.js';
import {
  hasPrefix,
  stripPrefix,
  parsePrefixedJson,
  validateAudioMetricsPayload,
  validateStatePayload,
  deriveLifecycleFromAudioState
} from './ipc_contract.js';
import {
  applyTranscriptVisibility,
  resolveTranscriptCollapseState,
  shouldResizeWindowForActiveMode
} from './renderer_ui_mode_strategy.js';

const MIN_WINDOW_HEIGHT = 124;
const EXPANDED_WINDOW_HEIGHT = 320;

let lastAudioState = 'inactive';
let lastLifecycleState = 'idle';
let lastIsDictating = false;
let isResponseCollapsed = false;

function hasTranscriptEntries() {
  const stream = document.getElementById('transcript-stream');
  return !!(stream && stream.querySelector('.transcript-entry'));
}

function mapLifecycleToTranscriptStatus(lifecycle, audioState, isDictating) {
  if (lifecycle === 'recording' || isDictating || audioState === 'dictation') {
    return 'recording';
  }
  if (
    lifecycle === 'stopping' ||
    lifecycle === 'transcribing' ||
    lifecycle === 'inserting' ||
    audioState === 'processing'
  ) {
    return 'processing';
  }
  if (lifecycle === 'listening' || audioState === 'activation' || audioState === 'preparing') {
    return 'listening';
  }
  return null;
}

function processDictationState(rawState) {
  if (!rawState) {
    return;
  }

  const baseState = {
    programActive: typeof rawState.programActive === 'boolean' ? rawState.programActive : true,
    audioState: rawState.audioState || (rawState.isDictating ? 'dictation' : 'inactive'),
    isDictating: !!rawState.isDictating,
    currentMode: rawState.currentMode !== undefined ? rawState.currentMode : null,
    wakeWordEnabled: rawState.wakeWordEnabled !== false,
    dictationLifecycle: rawState.dictationLifecycle
  };
  const normalizedState = validateStatePayload(baseState) || baseState;
  const audioState = normalizedState.audioState || 'inactive';
  const isDictating = !!normalizedState.isDictating;
  const lifecycle = normalizedState.dictationLifecycle || deriveLifecycleFromAudioState(audioState);

  updateStatusIndicator(normalizedState);

  const enteredRecording = lifecycle === 'recording' && lastLifecycleState !== 'recording';
  const leftRecording = lifecycle !== 'recording' && lastLifecycleState === 'recording';

  if (enteredRecording || (isDictating && !lastIsDictating)) {
    beginTranscriptSession();
    adjustWindowHeight(false, { forceState: 'collapsed' });
  } else if (leftRecording || (!isDictating && lastIsDictating)) {
    hideAudioSourceLevels();
    adjustWindowHeight(false, { forceState: 'expanded' });
  }

  const transcriptStatus = mapLifecycleToTranscriptStatus(lifecycle, audioState, isDictating);
  if (transcriptStatus === 'recording') {
    updateActiveTranscriptStatus('recording');
    adjustWindowHeight(false, { forceState: 'collapsed' });
  } else if (transcriptStatus === 'processing') {
    updateActiveTranscriptStatus('processing');
    adjustWindowHeight(false, { forceState: 'expanded' });
  } else if (transcriptStatus === 'listening') {
    updateActiveTranscriptStatus('listening');
    if (!isDictating) {
      const hasEntries = hasTranscriptEntries();
      adjustWindowHeight(hasEntries, { forceState: hasEntries ? 'expanded' : 'collapsed' });
    }
  }

  const enteredListening = lifecycle === 'listening' && lastLifecycleState !== 'listening';
  const enteredTranscribing =
    (lifecycle === 'stopping' || lifecycle === 'transcribing' || lifecycle === 'inserting') &&
    !(lastLifecycleState === 'stopping' || lastLifecycleState === 'transcribing' || lastLifecycleState === 'inserting');
  const becameInactive = lifecycle === 'idle' && lastLifecycleState !== 'idle';

  if (enteredListening && !isDictating) {
    const hasEntries = hasTranscriptEntries();
    adjustWindowHeight(hasEntries, { forceState: hasEntries ? 'expanded' : 'collapsed' });
  }

  if (enteredTranscribing && !isDictating) {
    adjustWindowHeight(false, { forceState: 'expanded' });
  }

  if (becameInactive) {
    const hasEntries = hasTranscriptEntries();
    adjustWindowHeight(hasEntries, hasEntries ? { forceState: 'expanded' } : { forceState: 'collapsed' });
  }

  lastIsDictating = isDictating;
  lastAudioState = audioState;
  lastLifecycleState = lifecycle;
}

function setResponseText(text, options = {}) {
  const cleaned = typeof text === 'string' ? text.trim() : '';
  const speaker = options.speaker || null;
  finalizeActiveTranscript(cleaned, { speaker });
  adjustWindowHeight(cleaned.length > 0, {
    forceState: 'expanded'
  });
}

function adjustWindowHeight(hasTranscript = false, options = {}) {
  const { forceState = null } = options;

  const responseArea = document.getElementById('response-area');
  if (!responseArea) {
    return;
  }

  const transcriptStream = document.getElementById('transcript-stream');
  const hasVisibleEntries = !!(transcriptStream && transcriptStream.querySelector('.transcript-entry'));

  const collapsed = resolveTranscriptCollapseState({
    forceState,
    hasEntries: hasTranscript || hasVisibleEntries,
    currentCollapsed: isResponseCollapsed
  });
  isResponseCollapsed = collapsed;
  applyTranscriptVisibility(collapsed);

  if (!shouldResizeWindowForActiveMode()) {
    return;
  }

  if (!window.electronAPI || typeof window.electronAPI.resizeWindow !== 'function') {
    return;
  }

  const responseHeight = collapsed ? 0 : responseArea.scrollHeight;
  const headerHeight = (document.getElementById('waveform-area')?.offsetHeight || 0)
    + (document.getElementById('control-bar')?.offsetHeight || 0)
    + 20;

  const effectiveHasTranscript = !collapsed && (hasTranscript || hasVisibleEntries);
  const desiredHeight = effectiveHasTranscript
    ? Math.max(EXPANDED_WINDOW_HEIGHT, responseHeight + headerHeight)
    : Math.max(MIN_WINDOW_HEIGHT, headerHeight);
  const currentHeight = window.innerHeight || 0;

  if (Math.abs(desiredHeight - currentHeight) > 8) {
    window.electronAPI.resizeWindow({ height: Math.round(desiredHeight) });
  }
}

function pushAmplitude(amplitudeValue) {
  if (!Number.isFinite(amplitudeValue)) {
    return;
  }
  const normalizedAmplitude = Math.max(0, Math.min(100, Math.round(amplitudeValue)));
  amplitudes.push(normalizedAmplitude);
  if (amplitudes.length > 100) {
    amplitudes.shift();
  }
}

function applyHandyLevels(levels, smooth = true) {
  if (!Array.isArray(levels)) {
    return;
  }
  for (let i = 0; i < handyLevels.length; i++) {
    const target = Number(levels[i]);
    const normalizedTarget = Number.isFinite(target) ? Math.min(Math.max(target, 0), 1) : 0;
    handyLevels[i] = smooth
      ? ((handyLevels[i] * 0.7) + (normalizedTarget * 0.3))
      : normalizedTarget;
  }
}

function updateAudioSourceLevels(sources) {
  const container = document.getElementById('audio-source-levels');
  if (!container) {
    return;
  }

  // Show container when we have sources
  container.classList.remove('is-hidden');

  // Reconcile DOM elements with source list
  const existingBars = container.querySelectorAll('.audio-source-level');
  const existingByName = new Map();
  existingBars.forEach((el) => existingByName.set(el.dataset.sourceName, el));

  const activeNames = new Set();
  for (const src of sources) {
    const name = src.name || 'Unknown';
    activeNames.add(name);
    let bar = existingByName.get(name);
    if (!bar) {
      bar = document.createElement('div');
      bar.className = 'audio-source-level';
      bar.dataset.sourceName = name;
      bar.innerHTML =
        '<span class="audio-source-level__name"></span>' +
        '<div class="audio-source-level__track">' +
        '<div class="audio-source-level__fill"></div>' +
        '</div>';
      container.appendChild(bar);
    }
    bar.querySelector('.audio-source-level__name').textContent = name;
    const level = Math.max(0, Math.min(1, Number(src.level) || 0));
    const fill = bar.querySelector('.audio-source-level__fill');
    fill.style.width = `${(level * 100).toFixed(1)}%`;

    // Color coding: green < 0.6, yellow < 0.85, red >= 0.85
    fill.classList.toggle('level-high', level >= 0.85);
    fill.classList.toggle('level-mid', level >= 0.6 && level < 0.85);
  }

  // Remove stale entries
  existingBars.forEach((el) => {
    if (!activeNames.has(el.dataset.sourceName)) {
      el.remove();
    }
  });
}

function hideAudioSourceLevels() {
  const container = document.getElementById('audio-source-levels');
  if (container) {
    container.classList.add('is-hidden');
    container.innerHTML = '';
  }
}

function applyAudioMetricsPayload(payload) {
  const normalizedPayload = validateAudioMetricsPayload(payload);
  if (!normalizedPayload) {
    return;
  }
  pushAmplitude(Number(normalizedPayload.amplitude));
  applyHandyLevels(normalizedPayload.levels, true);
}

export function registerIPCHandlers() {
  setTranscriptHeightCallback(adjustWindowHeight);
  isResponseCollapsed = resolveTranscriptCollapseState({
    forceState: null,
    hasEntries: false,
    currentCollapsed: false
  });
  applyTranscriptVisibility(isResponseCollapsed);

  if (window.electronAPI && typeof window.electronAPI.on === 'function') {
    window.electronAPI.on('ui-update', (payload) => {
      if (payload && payload.type === 'dictation_status_update') {
        processDictationState(payload);
      }
    });
  }

  if (window.electronAPI && window.electronAPI.handleFromPython) {
    window.electronAPI.handleFromPython((message) => {
      if (
        !hasPrefix(message, 'audioMetrics') &&
        !hasPrefix(message, 'audioAmplitudeLegacy') &&
        !hasPrefix(message, 'audioLevelsLegacy') &&
        !hasPrefix(message, 'audioSourceLevels') &&
        !hasPrefix(message, 'state')
      ) {
        console.log('[IPC_FROM_PYTHON_RAW]', message);
        logMessage(message, 'py');
      }

      if (hasPrefix(message, 'status')) {
        const statusPayload = stripPrefix(message, 'status') || '';
        const firstColon = statusPayload.indexOf(':');
        if (firstColon !== -1) {
          const color = statusPayload.substring(0, firstColon);
          const text = statusPayload.substring(firstColon + 1);
          handleStatusMessage(text, color);
        } else {
          handleStatusMessage(statusPayload, 'grey');
        }
      } else if (hasPrefix(message, 'finalTranscript')) {
        const rawTranscript = stripPrefix(message, 'finalTranscript') || '';
        // Try parsing as JSON for speaker-tagged transcripts
        try {
          const parsed = JSON.parse(rawTranscript);
          if (parsed && typeof parsed === 'object' && parsed.text) {
            setResponseText(parsed.text, { speaker: parsed.speaker || null });
          } else {
            setResponseText(rawTranscript);
          }
        } catch (_e) {
          // Plain text transcript (no speaker tag)
          setResponseText(rawTranscript);
        }
      } else if (hasPrefix(message, 'state')) {
        const stateData = validateStatePayload(parsePrefixedJson(message, 'state'));
        if (stateData) {
          processDictationState(stateData);
        } else {
          logMessage('Error parsing STATE payload.', 'error');
        }
      } else if (hasPrefix(message, 'audioMetrics')) {
        const payload = parsePrefixedJson(message, 'audioMetrics');
        if (payload) {
          applyAudioMetricsPayload(payload);
        } else {
          logMessage('Error parsing AUDIO_METRICS payload.', 'error');
        }
      } else if (hasPrefix(message, 'audioAmplitudeLegacy')) {
        const amplitudeValue = parseInt((stripPrefix(message, 'audioAmplitudeLegacy') || '0').trim(), 10);
        pushAmplitude(amplitudeValue);
      } else if (hasPrefix(message, 'audioLevelsLegacy')) {
        const payload = parsePrefixedJson(message, 'audioLevelsLegacy');
        if (payload) {
          applyHandyLevels(payload, true);
        } else {
          logMessage('Error parsing AUDIO_LEVELS payload.', 'error');
        }
      } else if (hasPrefix(message, 'audioSourceLevels')) {
        const payload = parsePrefixedJson(message, 'audioSourceLevels');
        if (Array.isArray(payload)) {
          updateAudioSourceLevels(payload);
        }
      } else if (hasPrefix(message, 'historyEntry')) {
        const entryData = parsePrefixedJson(message, 'historyEntry');
        if (entryData) {
          setLastHistoryEntry(entryData);
        } else {
          logMessage('Error parsing HISTORY_ENTRY payload.', 'error');
        }
      } else if (hasPrefix(message, 'retranscribeStart')) {
        const payload = stripPrefix(message, 'retranscribeStart') || '';
        if (payload.startsWith('error:')) {
          showRetranscribeProgress(payload.substring(6), true);
        } else {
          showRetranscribeProgress(payload, false);
          setRetranscribingState(true);
        }
      } else if (hasPrefix(message, 'retranscribeEnd')) {
        hideRetranscribeProgress();
        setRetranscribingState(false);
      } else if (hasPrefix(message, 'retranscribeQuickResult')) {
        const resultData = parsePrefixedJson(message, 'retranscribeQuickResult');
        if (resultData) {
          handleQuickRetranscribeResult(resultData);
        } else {
          logMessage('Error parsing RETRANSCRIBE_QUICK_RESULT payload.', 'error');
        }
      } else if (hasPrefix(message, 'hotkeys')) {
        logMessage(`Received Hotkeys: ${stripPrefix(message, 'hotkeys') || ''}`);
      } else if (message === 'BACKEND_READY') {
        logMessage('Python backend is ready.');
      } else if (message === 'SHUTDOWN_SIGNAL') {
        logMessage('Python backend is shutting down.');
        updateStatusIndicator({ audioState: 'inactive', programActive: false, dictationLifecycle: 'idle' });
      }
    });
  }

  if (window.electronAPI && window.electronAPI.handlePythonStderr) {
    window.electronAPI.handlePythonStderr((errorMessage) => {
      logMessage(errorMessage, 'error');
      console.log('Python Stderr received in renderer:', errorMessage);
      if (errorMessage.toLowerCase().includes('error')) {
        const dots = [document.getElementById('status-dot'), document.getElementById('handy-status-dot')].filter(Boolean);
        dots.forEach((dot) => {
          dot.style.backgroundColor = '#ff3b30';
          dot.style.boxShadow = '0 0 5px #ff3b30';
        });
      }
    });
  }
}

