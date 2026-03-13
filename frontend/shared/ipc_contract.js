// ipc_contract.js
// Shared IPC schema helpers for renderer modules.

const DEFAULT_CONTRACT = {
  version: 1,
  prefixes: {
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
    hotkeys: 'HOTKEYS:',
    audioSourceLevels: 'AUDIO_SOURCE_LEVELS:'
  },
  audioStates: ['inactive', 'preparing', 'activation', 'dictation', 'processing'],
  lifecycleStates: ['idle', 'listening', 'recording', 'stopping', 'transcribing', 'inserting', 'error']
};

let activeContract = { ...DEFAULT_CONTRACT };

const AUDIO_TO_LIFECYCLE = {
  inactive: 'idle',
  preparing: 'idle',
  activation: 'listening',
  dictation: 'recording',
  processing: 'transcribing'
};

function normalizeContract(raw) {
  const normalized = {
    version: Number.isFinite(Number(raw?.version)) ? Number(raw.version) : DEFAULT_CONTRACT.version,
    prefixes: {
      ...DEFAULT_CONTRACT.prefixes,
      ...(raw?.prefixes || {})
    },
    audioStates: Array.isArray(raw?.audioStates) ? raw.audioStates : DEFAULT_CONTRACT.audioStates,
    lifecycleStates: Array.isArray(raw?.lifecycleStates) ? raw.lifecycleStates : DEFAULT_CONTRACT.lifecycleStates
  };
  return normalized;
}

function getAudioStateSet() {
  return new Set(activeContract.audioStates || DEFAULT_CONTRACT.audioStates);
}

function getLifecycleStateSet() {
  return new Set(activeContract.lifecycleStates || DEFAULT_CONTRACT.lifecycleStates);
}

export function configureIpcContract(rawContract) {
  activeContract = normalizeContract(rawContract);
  return activeContract;
}

export function getContractVersion() {
  return Number.isFinite(Number(activeContract.version))
    ? Number(activeContract.version)
    : DEFAULT_CONTRACT.version;
}

export function getPrefix(name) {
  return (activeContract.prefixes && activeContract.prefixes[name]) || DEFAULT_CONTRACT.prefixes[name] || '';
}

export function hasPrefix(message, name) {
  return typeof message === 'string' && !!getPrefix(name) && message.startsWith(getPrefix(name));
}

export function stripPrefix(message, name) {
  if (!hasPrefix(message, name)) {
    return null;
  }
  return message.slice(getPrefix(name).length);
}

export function parsePrefixedJson(message, name) {
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

export function validateLifecycleState(value) {
  return typeof value === 'string' && getLifecycleStateSet().has(value);
}

export function deriveLifecycleFromAudioState(audioState) {
  if (typeof audioState !== 'string' || !getAudioStateSet().has(audioState)) {
    return 'idle';
  }
  return AUDIO_TO_LIFECYCLE[audioState] || 'idle';
}

export function validateStatePayload(payload) {
  if (!payload || typeof payload !== 'object') {
    return null;
  }

  const audioStates = getAudioStateSet();
  const audioState = audioStates.has(payload.audioState) ? payload.audioState : 'inactive';
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
    ipcSchemaVersion: getContractVersion()
  };
}

export function validateAudioMetricsPayload(payload) {
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

