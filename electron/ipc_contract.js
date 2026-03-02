// ipc_contract.js
// Shared IPC schema helpers for Electron main process modules.

const contract = require('../shared/ipc_contract.json');

const DEFAULT_PREFIXES = {
  state: 'STATE:',
  status: 'STATUS:',
  audioMetrics: 'AUDIO_METRICS:',
  audioAmplitudeLegacy: 'AUDIO_AMP:',
  audioLevelsLegacy: 'AUDIO_LEVELS:',
  finalTranscript: 'FINAL_TRANSCRIPT:',
  historyEntry: 'HISTORY_ENTRY:',
  retranscribeStart: 'RETRANSCRIBE_START:',
  retranscribeEnd: 'RETRANSCRIBE_END:',
  retranscribeQuickResult: 'RETRANSCRIBE_QUICK_RESULT:',
  hotkeys: 'HOTKEYS:'
};

const PREFIXES = Object.freeze({
  ...DEFAULT_PREFIXES,
  ...(contract?.prefixes || {})
});

const IPC_SCHEMA_VERSION = Number.isFinite(Number(contract?.version))
  ? Number(contract.version)
  : 1;

const AUDIO_STATES = new Set(
  Array.isArray(contract?.audioStates)
    ? contract.audioStates
    : ['inactive', 'preparing', 'activation', 'dictation', 'processing']
);
const AUDIO_STATES_LIST = Object.freeze(Array.from(AUDIO_STATES));

const LIFECYCLE_STATES = new Set(
  Array.isArray(contract?.lifecycleStates)
    ? contract.lifecycleStates
    : ['idle', 'listening', 'recording', 'stopping', 'transcribing', 'inserting', 'error']
);
const LIFECYCLE_STATES_LIST = Object.freeze(Array.from(LIFECYCLE_STATES));

const AUDIO_TO_LIFECYCLE = {
  inactive: 'idle',
  preparing: 'idle',
  activation: 'listening',
  dictation: 'recording',
  processing: 'transcribing'
};

function getPrefix(name) {
  return PREFIXES[name] || '';
}

function withPrefix(name, payload) {
  const prefix = getPrefix(name);
  if (!prefix) {
    throw new Error(`Unknown IPC prefix key: ${name}`);
  }
  if (typeof payload === 'string') {
    return `${prefix}${payload}`;
  }
  return `${prefix}${JSON.stringify(payload)}`;
}

function hasPrefix(message, name) {
  return typeof message === 'string' && !!getPrefix(name) && message.startsWith(getPrefix(name));
}

function stripPrefix(message, name) {
  if (!hasPrefix(message, name)) {
    return null;
  }
  return message.slice(getPrefix(name).length);
}

function parsePrefixedJson(message, name) {
  const payload = stripPrefix(message, name);
  if (payload === null) {
    return null;
  }
  try {
    return JSON.parse(payload);
  } catch (_error) {
    return null;
  }
}

function validateAudioState(value) {
  return typeof value === 'string' && AUDIO_STATES.has(value);
}

function validateLifecycleState(value) {
  return typeof value === 'string' && LIFECYCLE_STATES.has(value);
}

function deriveLifecycleFromAudioState(audioState) {
  if (!validateAudioState(audioState)) {
    return 'idle';
  }
  return AUDIO_TO_LIFECYCLE[audioState] || 'idle';
}

function validateAudioMetricsPayload(payload) {
  if (!payload || typeof payload !== 'object') {
    return null;
  }

  const amplitudeRaw = Number(payload.amplitude);
  const amplitude = Number.isFinite(amplitudeRaw)
    ? Math.max(0, Math.min(100, Math.round(amplitudeRaw)))
    : 0;

  const levelsRaw = Array.isArray(payload.levels) ? payload.levels : [];
  const levels = levelsRaw.map((value) => {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return 0;
    }
    return Math.max(0, Math.min(1, numeric));
  });

  return { amplitude, levels };
}

function validateStatePayload(payload) {
  if (!payload || typeof payload !== 'object') {
    return null;
  }

  const audioState = validateAudioState(payload.audioState) ? payload.audioState : 'inactive';
  const lifecycle = validateLifecycleState(payload.dictationLifecycle)
    ? payload.dictationLifecycle
    : deriveLifecycleFromAudioState(audioState);

  return {
    ...payload,
    audioState,
    programActive: Boolean(payload.programActive),
    isDictating: Boolean(payload.isDictating),
    wakeWordEnabled: payload.wakeWordEnabled !== false,
    dictationLifecycle: lifecycle,
    dictationLifecycleReason:
      typeof payload.dictationLifecycleReason === 'string' ? payload.dictationLifecycleReason : '',
    ipcSchemaVersion: IPC_SCHEMA_VERSION
  };
}

module.exports = {
  IPC_SCHEMA_VERSION,
  PREFIXES,
  AUDIO_STATES_LIST,
  LIFECYCLE_STATES_LIST,
  getPrefix,
  withPrefix,
  hasPrefix,
  stripPrefix,
  parsePrefixedJson,
  validateAudioMetricsPayload,
  validateStatePayload,
  validateLifecycleState
};
