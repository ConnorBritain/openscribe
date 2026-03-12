console.log('Settings renderer script loaded.');

// --- DOM Elements ---
const sidebarLinks = {
  wakewords: document.getElementById('nav-wakewords'),
  asr: document.getElementById('nav-asr'),
  vocabulary: document.getElementById('nav-vocabulary'),
  cloudapi: document.getElementById('nav-cloudapi'),
  about: document.getElementById('nav-about'),
};
const vocabularyNavBadge = document.getElementById('nav-vocabulary-badge');
const sections = {
  wakewords: document.getElementById('section-wakewords'),
  asr: document.getElementById('section-asr'),
  vocabulary: document.getElementById('section-vocabulary'),
  cloudapi: document.getElementById('section-cloudapi'),
  about: document.getElementById('section-about'),
};

const ASR_MODELS = [
  { id: 'mlx-community/whisper-large-v3-turbo', name: 'Whisper (large-v3-turbo) – Recommended' },
  { id: 'mlx-community/distil-whisper-large-v3', name: 'Distil-Whisper (large-v3, fast) – ~3x faster than turbo' },
  { id: 'mlx-community/parakeet-tdt-0.6b-v2', name: 'Parakeet-TDT-0.6B-v2 – Requires parakeet-mlx' },
  { id: 'mlx-community/parakeet-tdt-0.6b-v3', name: 'Parakeet-TDT-0.6B-v3 – Latest MLX build' },
  { id: 'mlx-community/Voxtral-Mini-3B-2507-bf16', name: 'Voxtral Mini 3B (bf16) – MLX Audio' },
  { id: 'google/medasr', name: 'MedASR (Medical) – Optimized for medical dictation' },
  { id: 'apple:speech:ondevice', name: 'Apple Speech (on-device, macOS) – No model download' },
  { id: 'openai:whisper-1', name: 'OpenAI Whisper – Cloud API (requires API key)' },
  { id: 'openai:gpt-4o-transcribe', name: 'OpenAI GPT-4o Transcribe – Cloud API (requires API key)' },
  { id: 'google:chirp_2', name: 'Google Chirp 2 – Cloud API (requires key file)' }
];

// ASR Model Elements
const asrModelSelect = document.getElementById('asr-model-select');
const secondaryAsrModelSelect = document.getElementById('secondary-asr-model-select');
const saveAsrModelButton = document.getElementById('save-asr-model-button');
const medgemmaOption = document.getElementById('medgemma-option');
const useMedgemmaToggle = document.getElementById('use-medgemma-toggle');
const asrModelStatus = document.getElementById('asr-model-status');
// Wake Words Elements (Updated)
const wakeWordsDictateInput = document.getElementById('wake-words-dictate-input');
const wakeWordEnabledToggle = document.getElementById('wake-word-enabled-toggle');
const filterFillerToggle = document.getElementById('filter-filler-toggle');
const fillerWordsInput = document.getElementById('filler-words-input');
const autoStopToggle = document.getElementById('auto-stop-toggle');
const uiModeSelect = document.getElementById('ui-mode-select');
const saveDictationButton = document.getElementById('save-dictation-button');
const wakeWordsStatus = document.getElementById('wake-words-status');
const microphoneSelect = document.getElementById('microphone-select');
const refreshMicrophonesButton = document.getElementById('refresh-microphones-button');
const transcribeShortcutButton = document.getElementById('transcribe-shortcut-button');
const stopShortcutButton = document.getElementById('stop-transcribing-shortcut-button');
const retranscribeShortcutButton = document.getElementById('retranscribe-shortcut-button');
const transcribeShortcutReset = document.getElementById('transcribe-shortcut-reset');
const stopShortcutReset = document.getElementById('stop-transcribing-shortcut-reset');
const retranscribeShortcutReset = document.getElementById('retranscribe-shortcut-reset');
// Vocabulary Elements
const medicationObservedInput = document.getElementById('med-map-observed');
const medicationCanonicalInput = document.getElementById('med-map-canonical');
const medicationAddButton = document.getElementById('med-map-add-button');
const medicationSearchInput = document.getElementById('med-map-search');
const medicationMapList = document.getElementById('med-map-list');
const medicationStatsText = document.getElementById('med-map-stats-text');
const medicationReviewList = document.getElementById('med-review-list');
const medicationReportPathInput = document.getElementById('med-report-path');
const medicationImportButton = document.getElementById('med-import-button');
const medicationAutoLearnToggle = document.getElementById('med-autolearn-toggle');
const medicationAutoLearnRunNowButton = document.getElementById('med-autolearn-run-now');
const medicationAutoLearnSummary = document.getElementById('med-autolearn-last-summary');
const vocabularyStatus = document.getElementById('vocabulary-status');

const DEFAULT_SHORTCUTS = {
  transcribe: 'Option+Space',
  stopTranscribing: 'Cmd+Shift+S',
  retranscribeBackup: 'Ctrl+Option+R'
};
const MODIFIER_ORDER = ['Cmd', 'Ctrl', 'Option', 'Shift'];

let shortcutBindings = { ...DEFAULT_SHORTCUTS };
let activeShortcutCapture = null;
let selectedMicrophoneId = 'default';
let backendHotkeysSuspended = false;

const shortcutButtonMap = {
  transcribe: transcribeShortcutButton,
  stopTranscribing: stopShortcutButton,
  retranscribeBackup: retranscribeShortcutButton
};
const shortcutLabelMap = {
  transcribe: 'Transcribe Shortcut',
  stopTranscribing: 'Stop Transcribing Shortcut',
  retranscribeBackup: 'Re-transcribe With Backup Model',
};


// --- Navigation ---
function showSection(sectionId) {
  // Hide all sections
  Object.values(sections).forEach(section => section.style.display = 'none');
  // Deactivate all sidebar links
  Object.values(sidebarLinks).forEach(link => link.classList.remove('active'));

  // Show the target section
  if (sections[sectionId]) {
    sections[sectionId].style.display = 'block';
  }
  // Activate the target sidebar link
  if (sidebarLinks[sectionId]) {
    sidebarLinks[sectionId].classList.add('active');
  }
}

Object.keys(sidebarLinks).forEach(key => {
  if (sidebarLinks[key]) {
    sidebarLinks[key].addEventListener('click', () => showSection(key));
  }
});

function normalizeShortcutString(shortcut) {
  if (typeof shortcut !== 'string' || !shortcut.trim()) {
    return '';
  }
  const tokens = shortcut
    .split('+')
    .map((token) => token.trim())
    .filter(Boolean);

  const normalizedModifiers = [];
  let normalizedMainKey = '';
  tokens.forEach((token) => {
    const lowered = token.toLowerCase();
    if (lowered === 'command' || lowered === 'cmd') normalizedModifiers.push('Cmd');
    else if (lowered === 'control' || lowered === 'ctrl') normalizedModifiers.push('Ctrl');
    else if (lowered === 'option' || lowered === 'alt') normalizedModifiers.push('Option');
    else if (lowered === 'shift') normalizedModifiers.push('Shift');
    else if (lowered === 'space') normalizedMainKey = 'Space';
    else if (token.length === 1 && /[a-z0-9]/i.test(token)) normalizedMainKey = token.toUpperCase();
  });

  const uniqueModifiers = [...new Set(normalizedModifiers)];
  const ordered = [];
  MODIFIER_ORDER.forEach((modifier) => {
    if (uniqueModifiers.includes(modifier)) {
      ordered.push(modifier);
    }
  });
  if (normalizedMainKey) {
    ordered.push(normalizedMainKey);
  }
  return ordered.join('+');
}

function formatShortcutLabel(shortcut) {
  const normalized = normalizeShortcutString(shortcut);
  return normalized ? normalized.replace(/\+/g, ' + ') : 'Set Shortcut';
}

function sanitizeShortcut(shortcut, fallback) {
  const normalized = normalizeShortcutString(shortcut);
  const tokens = normalized.split('+').filter(Boolean);
  if (tokens.length < 2) {
    return fallback;
  }
  const mainKey = tokens[tokens.length - 1];
  const modifiers = tokens.slice(0, -1);
  const hasValidModifiers = modifiers.length > 0 && modifiers.every((token) => MODIFIER_ORDER.includes(token));
  const hasValidMainKey = mainKey === 'Space' || /^[A-Z0-9]$/.test(mainKey);
  if (!hasValidModifiers || !hasValidMainKey) {
    return fallback;
  }
  return normalized;
}

function setShortcutStatus(message, isError = false) {
  if (!wakeWordsStatus) return;
  wakeWordsStatus.textContent = message || '';
  wakeWordsStatus.style.color = isError ? 'red' : 'green';
  if (!message) {
    return;
  }
  setTimeout(() => {
    if (wakeWordsStatus.textContent === message) {
      wakeWordsStatus.textContent = '';
    }
  }, 3000);
}

function isAllowedSharedShortcut(firstKey, secondKey) {
  const pair = new Set([firstKey, secondKey]);
  return pair.size === 2 && pair.has('transcribe') && pair.has('stopTranscribing');
}

function getShortcutConflict(conflictingKey, shortcutValue, bindings = shortcutBindings) {
  return Object.entries(bindings).find(([key, value]) => {
    if (key === conflictingKey) return false;
    if (isAllowedSharedShortcut(key, conflictingKey)) return false;
    return normalizeShortcutString(value) === normalizeShortcutString(shortcutValue);
  }) || null;
}

function normalizeShortcutBindings(inputBindings) {
  const orderedKeys = ['transcribe', 'stopTranscribing', 'retranscribeBackup'];
  const normalized = {
    transcribe: sanitizeShortcut(inputBindings?.transcribe, DEFAULT_SHORTCUTS.transcribe),
    stopTranscribing: sanitizeShortcut(inputBindings?.stopTranscribing, DEFAULT_SHORTCUTS.stopTranscribing),
    retranscribeBackup: sanitizeShortcut(inputBindings?.retranscribeBackup, DEFAULT_SHORTCUTS.retranscribeBackup),
  };
  let hadConflict = false;

  orderedKeys.forEach((leftKey, leftIndex) => {
    const leftValue = normalizeShortcutString(normalized[leftKey]);
    if (!leftValue) {
      return;
    }
    orderedKeys.slice(leftIndex + 1).forEach((rightKey) => {
      const rightValue = normalizeShortcutString(normalized[rightKey]);
      if (!rightValue) {
        return;
      }
      if (leftValue !== rightValue) {
        return;
      }
      if (isAllowedSharedShortcut(leftKey, rightKey)) {
        return;
      }

      hadConflict = true;
      normalized[rightKey] = DEFAULT_SHORTCUTS[rightKey];
      if (
        normalizeShortcutString(normalized[rightKey]) === normalizeShortcutString(normalized[leftKey]) &&
        !isAllowedSharedShortcut(leftKey, rightKey)
      ) {
        normalized[rightKey] = '';
      }
    });
  });

  return { bindings: normalized, hadConflict };
}

async function setBackendHotkeysSuspended(suspended) {
  const targetState = !!suspended;
  if (backendHotkeysSuspended === targetState) {
    return;
  }
  if (!window.settingsAPI || typeof window.settingsAPI.setHotkeysSuspended !== 'function') {
    backendHotkeysSuspended = targetState;
    return;
  }
  try {
    const result = await window.settingsAPI.setHotkeysSuspended(targetState);
    if (!result || result.success === false) {
      console.warn('Failed to update backend hotkey suspension state:', result?.error || result);
      return;
    }
    backendHotkeysSuspended = targetState;
  } catch (error) {
    console.error('Error toggling backend hotkey suspension state:', error);
  }
}

function renderShortcutButtons() {
  Object.entries(shortcutButtonMap).forEach(([shortcutKey, button]) => {
    if (!button) return;
    const value = shortcutBindings[shortcutKey] || DEFAULT_SHORTCUTS[shortcutKey];
    const isCapturing = activeShortcutCapture === shortcutKey;
    button.textContent = isCapturing ? 'Press shortcut...' : formatShortcutLabel(value);
    button.classList.toggle('capturing', isCapturing);
  });
}

function buildShortcutFromKeyboardEvent(event) {
  const modifiers = [];
  if (event.metaKey) modifiers.push('Cmd');
  if (event.ctrlKey) modifiers.push('Ctrl');
  if (event.altKey) modifiers.push('Option');
  if (event.shiftKey) modifiers.push('Shift');

  let keyName = '';
  if (event.code === 'Space') {
    keyName = 'Space';
  } else if (event.key && event.key.length === 1 && /[a-z0-9]/i.test(event.key)) {
    keyName = event.key.toUpperCase();
  }

  if (!keyName || modifiers.length === 0) {
    return null;
  }
  return normalizeShortcutString([...modifiers, keyName].join('+'));
}

function beginShortcutCapture(shortcutKey) {
  if (activeShortcutCapture === shortcutKey) {
    cancelShortcutCapture();
    return;
  }
  void setBackendHotkeysSuspended(true);
  activeShortcutCapture = shortcutKey;
  renderShortcutButtons();
}

function cancelShortcutCapture() {
  activeShortcutCapture = null;
  renderShortcutButtons();
  void setBackendHotkeysSuspended(false);
}

document.addEventListener('keydown', (event) => {
  if (!activeShortcutCapture) {
    return;
  }
  event.preventDefault();
  event.stopPropagation();

  if (event.key === 'Escape') {
    cancelShortcutCapture();
    return;
  }

  const shortcut = buildShortcutFromKeyboardEvent(event);
  if (!shortcut) {
    return;
  }

  const conflictEntry = getShortcutConflict(activeShortcutCapture, shortcut);
  if (conflictEntry) {
    const [conflictKey] = conflictEntry;
    setShortcutStatus(
      `${formatShortcutLabel(shortcut)} is already used by ${shortcutLabelMap[conflictKey] || conflictKey}.`,
      true,
    );
    return;
  }

  shortcutBindings[activeShortcutCapture] = shortcut;
  setShortcutStatus(
    `${shortcutLabelMap[activeShortcutCapture] || 'Shortcut'} set to ${formatShortcutLabel(shortcut)}.`,
    false,
  );
  cancelShortcutCapture();
});

function initializeShortcutControls() {
  Object.entries(shortcutButtonMap).forEach(([shortcutKey, button]) => {
    if (!button) return;
    button.addEventListener('mousedown', () => {
      void setBackendHotkeysSuspended(true);
    });
    button.addEventListener('click', () => beginShortcutCapture(shortcutKey));
  });

  if (transcribeShortcutReset) {
    transcribeShortcutReset.addEventListener('click', () => {
      shortcutBindings.transcribe = DEFAULT_SHORTCUTS.transcribe;
      renderShortcutButtons();
      setShortcutStatus(`${shortcutLabelMap.transcribe} reset.`, false);
    });
  }
  if (stopShortcutReset) {
    stopShortcutReset.addEventListener('click', () => {
      shortcutBindings.stopTranscribing = DEFAULT_SHORTCUTS.stopTranscribing;
      renderShortcutButtons();
      setShortcutStatus(`${shortcutLabelMap.stopTranscribing} reset.`, false);
    });
  }
  if (retranscribeShortcutReset) {
    retranscribeShortcutReset.addEventListener('click', () => {
      shortcutBindings.retranscribeBackup = DEFAULT_SHORTCUTS.retranscribeBackup;
      renderShortcutButtons();
      setShortcutStatus(`${shortcutLabelMap.retranscribeBackup} reset.`, false);
    });
  }
}

function populateMicrophoneDropdown(devices, preferredId = 'default') {
  if (!microphoneSelect) return;
  microphoneSelect.innerHTML = '';

  const normalizedPreferred = preferredId || 'default';
  const sourceDevices = Array.isArray(devices) && devices.length > 0
    ? devices
    : [{ id: 'default', name: 'Default', isDefault: true }];

  sourceDevices.forEach((device) => {
    const option = document.createElement('option');
    option.value = String(device.id);
    option.textContent = device.name || 'Unnamed Microphone';
    microphoneSelect.appendChild(option);
  });

  microphoneSelect.value = sourceDevices.some((device) => String(device.id) === String(normalizedPreferred))
    ? String(normalizedPreferred)
    : 'default';
  selectedMicrophoneId = microphoneSelect.value;
}

function initializeMicrophoneControls() {
  if (microphoneSelect) {
    microphoneSelect.addEventListener('change', () => {
      selectedMicrophoneId = microphoneSelect.value || 'default';
    });
  }

  if (refreshMicrophonesButton) {
    refreshMicrophonesButton.addEventListener('click', () => {
      refreshMicrophones(selectedMicrophoneId);
    });
  }
}

async function refreshMicrophones(preferredId = selectedMicrophoneId) {
  if (!window.settingsAPI || typeof window.settingsAPI.listMicrophones !== 'function') {
    populateMicrophoneDropdown([], preferredId);
    return;
  }

  try {
    if (refreshMicrophonesButton) {
      refreshMicrophonesButton.disabled = true;
    }
    const result = await window.settingsAPI.listMicrophones();
    const devices = result && result.success ? result.devices : [];
    populateMicrophoneDropdown(devices, preferredId);
  } catch (error) {
    console.error('Failed to refresh microphones:', error);
    populateMicrophoneDropdown([], preferredId);
  } finally {
    if (refreshMicrophonesButton) {
      refreshMicrophonesButton.disabled = false;
    }
  }
}

// --- Model Population ---
function populateAsrModelDropdown(selectedAsrModel) {
  if (!asrModelSelect) {
    return;
  }

  asrModelSelect.innerHTML = '';
  ASR_MODELS.forEach(model => {
    const option = document.createElement('option');
    option.value = model.id;
    option.textContent = model.name;
    asrModelSelect.appendChild(option);
  });

  const modelToSelect = selectedAsrModel || (ASR_MODELS.length > 0 ? ASR_MODELS[0].id : '');
  if (modelToSelect) {
    asrModelSelect.value = modelToSelect;
  }

  // Show/hide MedGemma option based on model selection
  updateMedgemmaVisibility();
}

function populateSecondaryModelDropdown(secondaryAsrModel) {
  if (!secondaryAsrModelSelect) return;

  secondaryAsrModelSelect.innerHTML = '';
  const noneOption = document.createElement('option');
  noneOption.value = '';
  noneOption.textContent = 'None';
  secondaryAsrModelSelect.appendChild(noneOption);

  ASR_MODELS.forEach(model => {
    const option = document.createElement('option');
    option.value = model.id;
    option.textContent = model.name;
    secondaryAsrModelSelect.appendChild(option);
  });

  if (secondaryAsrModel) {
    secondaryAsrModelSelect.value = secondaryAsrModel;
  }
}

function updateMedgemmaVisibility() {
  if (asrModelSelect && medgemmaOption) {
    const isMedAsr = asrModelSelect.value === 'google/medasr';
    medgemmaOption.style.display = isMedAsr ? 'block' : 'none';
  }
}

// Listen for ASR model changes
if (asrModelSelect) {
  asrModelSelect.addEventListener('change', updateMedgemmaVisibility);
}


// --- Load Settings ---
async function loadAndPopulateSettings() {
  console.log('DEBUG: Settings DOM loaded. Requesting settings...');
  try {
    const settings = await window.settingsAPI.loadSettings();

    console.log('DEBUG: Settings loaded from main:', settings);

    // Populate wake words
    if (settings.wakeWords && typeof settings.wakeWords === 'object') {
      wakeWordsDictateInput.value = (settings.wakeWords.dictate || []).join(', ');
    } else {
      console.warn('Wake words setting missing or invalid. Resetting to defaults.');
      wakeWordsDictateInput.value = '';
    }
    if (wakeWordEnabledToggle) {
      wakeWordEnabledToggle.checked = settings.wakeWordEnabled !== false;
    }

    // Populate filler-word controls
    if (filterFillerToggle) {
      filterFillerToggle.checked = settings.filterFillerWords !== false;
    }
    if (fillerWordsInput) {
      const fillerWords = Array.isArray(settings.fillerWords) && settings.fillerWords.length > 0
        ? settings.fillerWords
        : ['um', 'uh', 'ah', 'er', 'hmm', 'mm', 'mhm'];
      fillerWordsInput.value = fillerWords.join(', ');
    }
    if (autoStopToggle) {
      autoStopToggle.checked = settings.autoStopOnSilence !== false;
    }
    if (medicationAutoLearnToggle) {
      medicationAutoLearnToggle.checked = settings.medicationAutoLearnEnabled !== false;
    }
    if (uiModeSelect) {
      uiModeSelect.value = settings.uiMode === 'handy' ? 'handy' : 'classic';
    }
    selectedMicrophoneId = String(settings.selectedMicrophoneId || 'default');

    const loadedShortcutBindings = {
      transcribe: sanitizeShortcut(settings.transcribeShortcut, DEFAULT_SHORTCUTS.transcribe),
      stopTranscribing: sanitizeShortcut(settings.stopTranscribingShortcut, DEFAULT_SHORTCUTS.stopTranscribing),
      retranscribeBackup: sanitizeShortcut(settings.retranscribeBackupShortcut, DEFAULT_SHORTCUTS.retranscribeBackup),
    };
    const normalizedShortcutState = normalizeShortcutBindings(loadedShortcutBindings);
    shortcutBindings = normalizedShortcutState.bindings;
    renderShortcutButtons();
    if (normalizedShortcutState.hadConflict) {
      setShortcutStatus('Duplicate shortcut settings were detected and auto-corrected. Save to keep changes.', true);
    }
    await refreshMicrophones(selectedMicrophoneId);

    // Populate ASR model dropdown
    populateAsrModelDropdown(settings.selectedAsrModel);

    // Populate secondary ASR model dropdown
    populateSecondaryModelDropdown(settings.secondaryAsrModel || '');

    // Load MedGemma toggle state
    if (useMedgemmaToggle) {
      useMedgemmaToggle.checked = settings.useMedGemmaPostProcessing === true;
    }

    // Load Cloud API key status (masked display)
    refreshSettingsApiKeyStatus();
  } catch (error) {
    console.error('ERROR: Error loading settings:', error);
    if (wakeWordsStatus) {
      wakeWordsStatus.textContent = 'Error loading settings. Please retry.';
      wakeWordsStatus.style.color = 'red';
    }
  }
}

// --- Save Settings ---

// Save ASR Model
if (saveAsrModelButton) {
  saveAsrModelButton.addEventListener('click', async () => {
    if (!asrModelSelect) {
      return;
    }
    const selectedAsrModel = asrModelSelect.value;
    if (!selectedAsrModel) {
      asrModelStatus.textContent = 'Select an ASR model first.';
      asrModelStatus.style.color = 'red';
      return;
    }

    try {
      saveAsrModelButton.disabled = true;
      asrModelSelect.disabled = true;
      asrModelStatus.textContent = 'Preparing model assets…';
      asrModelStatus.style.color = '#ffb400';

      const ensureResult = await window.settingsAPI.ensureModel(selectedAsrModel);
      if (!ensureResult || ensureResult.success === false) {
        const errorMessage = ensureResult?.error || 'Model preparation failed.';
        throw new Error(errorMessage);
      }

      // Also save MedGemma toggle if MedASR is selected
      const useMedGemmaPostProcessing = useMedgemmaToggle ? useMedgemmaToggle.checked : false;
      const secondaryAsrModel = secondaryAsrModelSelect ? secondaryAsrModelSelect.value || null : null;
      window.settingsAPI.saveSettings({ selectedAsrModel, useMedGemmaPostProcessing, secondaryAsrModel });
      asrModelStatus.textContent = 'ASR model settings saved!';
      asrModelStatus.style.color = 'green';
      setTimeout(() => { asrModelStatus.textContent = ''; }, 3500);
    } catch (error) {
      console.error('Failed to prepare ASR model', error);
      asrModelStatus.textContent = `Model setup failed: ${error?.message || error}`;
      asrModelStatus.style.color = 'red';
    } finally {
      saveAsrModelButton.disabled = false;
      asrModelSelect.disabled = false;
    }
  });
}

// Helper function to parse comma-separated string into array
const parseWakeWords = (inputString) => {
  return (inputString || '').split(',')
    .map(word => word.trim())
    .filter(word => word.length > 0);
};

function validateShortcutBindings(bindings) {
  const entries = Object.entries(bindings).map(([id, value]) => [id, sanitizeShortcut(value, '')]);
  const invalid = entries.find(([, value]) => !value);
  if (invalid) {
    return { valid: false, error: 'Each shortcut must include at least one modifier and one letter/number or Space.' };
  }
  for (let leftIndex = 0; leftIndex < entries.length; leftIndex += 1) {
    const [leftKey, leftValue] = entries[leftIndex];
    for (let rightIndex = leftIndex + 1; rightIndex < entries.length; rightIndex += 1) {
      const [rightKey, rightValue] = entries[rightIndex];
      if (leftValue !== rightValue) {
        continue;
      }
      if (isAllowedSharedShortcut(leftKey, rightKey)) {
        continue;
      }
      return { valid: false, error: 'Re-transcribe shortcut must be different from Transcribe/Stop shortcuts.' };
    }
  }
  return { valid: true };
}

if (saveDictationButton) {
  saveDictationButton.addEventListener('click', () => {
    const shortcutValidation = validateShortcutBindings(shortcutBindings);
    if (!shortcutValidation.valid) {
      wakeWordsStatus.textContent = shortcutValidation.error;
      wakeWordsStatus.style.color = 'red';
      return;
    }

    const wakeWordsData = {
      dictate: parseWakeWords(wakeWordsDictateInput.value)
    };

    const fillerWords = parseWakeWords(fillerWordsInput.value);
    const payload = {
      wakeWords: wakeWordsData,
      filterFillerWords: !!filterFillerToggle.checked,
      fillerWords,
      autoStopOnSilence: autoStopToggle ? !!autoStopToggle.checked : true,
      wakeWordEnabled: wakeWordEnabledToggle ? !!wakeWordEnabledToggle.checked : true,
      uiMode: uiModeSelect ? uiModeSelect.value : 'classic',
      selectedMicrophoneId: selectedMicrophoneId || 'default',
      transcribeShortcut: shortcutBindings.transcribe,
      stopTranscribingShortcut: shortcutBindings.stopTranscribing,
      retranscribeBackupShortcut: shortcutBindings.retranscribeBackup
    };

    console.log('DEBUG: Saving dictation settings:', payload);
    window.settingsAPI.saveSettings(payload);
    wakeWordsStatus.textContent = 'Dictation settings saved!';
    wakeWordsStatus.style.color = 'green';
    setTimeout(() => { wakeWordsStatus.textContent = ''; }, 3000);
  });
}

// --- Vocabulary Management ---
let currentMedicationMappings = [];
let currentMedicationReviews = [];
let vocabularyStatusTimer = null;

function setVocabularyStatus(message, { isError = false, timeoutMs = 3500 } = {}) {
  if (!vocabularyStatus) {
    return;
  }
  vocabularyStatus.textContent = message || '';
  vocabularyStatus.style.color = isError ? 'red' : 'green';

  if (vocabularyStatusTimer) {
    clearTimeout(vocabularyStatusTimer);
    vocabularyStatusTimer = null;
  }
  if (message && timeoutMs > 0) {
    vocabularyStatusTimer = setTimeout(() => {
      vocabularyStatus.textContent = '';
      vocabularyStatusTimer = null;
    }, timeoutMs);
  }
}

function updateVocabularyNavBadge(count) {
  if (!vocabularyNavBadge) {
    return;
  }
  const numeric = Math.max(0, Number(count) || 0);
  vocabularyNavBadge.textContent = numeric > 99 ? '99+' : String(numeric);
  vocabularyNavBadge.classList.toggle('hidden', numeric === 0);
}

function formatRunTimestamp(value) {
  if (!value) {
    return 'Never';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString();
}

function renderMedicationAutoLearnSummary(summary) {
  if (!medicationAutoLearnSummary) {
    return;
  }
  if (!summary || typeof summary !== 'object') {
    medicationAutoLearnSummary.textContent = 'No auto-learn runs yet.';
    return;
  }

  const scanned = Number(summary.scannedRecords || 0);
  const imported = Number(summary.importedMappings || 0);
  const queued = Number(summary.queuedReviews || 0);
  const pending = Number(summary.pendingReviews || 0);
  const runReason = summary.runReason || 'auto';
  const durationMs = Number(summary.durationMs || 0);
  const rendered = [
    `Last run: ${formatRunTimestamp(summary.lastRunAt)} (${runReason})`,
    `Scanned ${scanned} records, imported ${imported}, queued ${queued}, pending ${pending}`,
    `Duration: ${durationMs} ms`,
  ];
  if (summary.error) {
    rendered.push(`Error: ${summary.error}`);
  }
  medicationAutoLearnSummary.textContent = rendered.join(' • ');
}

function makeEmptyState(text) {
  const empty = document.createElement('div');
  empty.style.cssText = 'text-align: center; padding: 24px; color: #666;';
  empty.textContent = text;
  return empty;
}

function truncateText(value, maxLen = 140) {
  const text = String(value || '');
  if (text.length <= maxLen) {
    return text;
  }
  return `${text.slice(0, maxLen - 1)}…`;
}

function renderMedicationStats() {
  if (!medicationStatsText) {
    return;
  }
  const totalMappings = currentMedicationMappings.length;
  const pendingReviews = currentMedicationReviews.length;
  const totalUsage = currentMedicationMappings
    .reduce((sum, row) => sum + Number(row.usage_count || 0), 0);
  medicationStatsText.textContent = `${totalMappings} mappings • ${pendingReviews} pending reviews • ${totalUsage} auto-applies`;
  updateVocabularyNavBadge(pendingReviews);
}

function renderMedicationMappings() {
  if (!medicationMapList) {
    return;
  }
  const query = (medicationSearchInput?.value || '').trim().toLowerCase();
  const rows = query
    ? currentMedicationMappings.filter((row) => {
      const haystack = `${row.observed || ''} ${row.canonical || ''}`.toLowerCase();
      return haystack.includes(query);
    })
    : currentMedicationMappings;

  medicationMapList.innerHTML = '';
  if (!rows.length) {
    medicationMapList.appendChild(makeEmptyState('No medication mappings yet.'));
    return;
  }

  rows.forEach((row) => {
    const item = document.createElement('div');
    item.style.cssText = 'border-bottom: 1px solid #ececec; padding: 12px 14px; display: flex; justify-content: space-between; gap: 10px; align-items: flex-start;';

    const info = document.createElement('div');
    const heading = document.createElement('div');
    heading.style.cssText = 'font-weight: 600; color: #1f2933;';
    heading.textContent = `${row.observed} -> ${row.canonical}`;
    info.appendChild(heading);

    const meta = document.createElement('div');
    meta.style.cssText = 'font-size: 12px; color: #667085; margin-top: 4px;';
    meta.textContent = `source: ${row.source || 'manual'} • seen ${row.occurrence_count || 0}x • used ${row.usage_count || 0}x`;
    info.appendChild(meta);

    const controls = document.createElement('div');
    const deleteBtn = document.createElement('button');
    deleteBtn.textContent = 'Delete';
    deleteBtn.style.cssText = 'background: #dc3545; color: white; border: none; padding: 7px 10px; border-radius: 4px; cursor: pointer;';
    deleteBtn.addEventListener('click', () => deleteMedicationMapping(row.observed));
    controls.appendChild(deleteBtn);

    item.appendChild(info);
    item.appendChild(controls);
    medicationMapList.appendChild(item);
  });
}

async function deleteMedicationMapping(observed) {
  if (!observed) {
    return;
  }
  if (!confirm(`Delete mapping for "${observed}"?`)) {
    return;
  }
  try {
    const result = await window.settingsAPI.callVocabularyAPI('delete_medication_mapping', {
      observed
    });
    if (!result || result.success === false) {
      throw new Error(result?.error || 'Failed to delete medication mapping.');
    }
    setVocabularyStatus(result.message || 'Medication mapping deleted.');
    await loadVocabularyData();
  } catch (error) {
    setVocabularyStatus(error?.message || 'Failed to delete medication mapping.', { isError: true });
  }
}

function renderMedicationReviewQueue() {
  if (!medicationReviewList) {
    return;
  }
  medicationReviewList.innerHTML = '';
  if (!currentMedicationReviews.length) {
    medicationReviewList.appendChild(makeEmptyState('No pending review items.'));
    return;
  }

  currentMedicationReviews.forEach((review) => {
    const item = document.createElement('div');
    item.style.cssText = 'border-bottom: 1px solid #ececec; padding: 12px 14px;';

    const heading = document.createElement('div');
    heading.style.cssText = 'font-weight: 600; color: #1f2933;';
    heading.textContent = `${review.observed} -> ${review.suggested}`;
    item.appendChild(heading);

    const meta = document.createElement('div');
    meta.style.cssText = 'font-size: 12px; color: #667085; margin-top: 4px;';
    meta.textContent = `confidence: ${review.confidence || 'unknown'} • seen ${review.occurrence_count || 0}x across ${review.entry_count || 0} entries`;
    item.appendChild(meta);

    if (review.sample_context) {
      const context = document.createElement('div');
      context.style.cssText = 'font-size: 12px; color: #475467; margin-top: 6px;';
      context.textContent = `Context: ${truncateText(review.sample_context, 180)}`;
      item.appendChild(context);
    }

    const actions = document.createElement('div');
    actions.style.cssText = 'display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; align-items: center;';

    const canonicalInput = document.createElement('input');
    canonicalInput.type = 'text';
    canonicalInput.value = review.suggested || '';
    canonicalInput.style.cssText = 'flex: 1 1 220px; min-width: 200px; padding: 7px 9px; border: 1px solid #d0d5dd; border-radius: 4px;';
    actions.appendChild(canonicalInput);

    const acceptBtn = document.createElement('button');
    acceptBtn.textContent = 'Accept';
    acceptBtn.style.cssText = 'background: #28a745; color: white; border: none; padding: 7px 10px; border-radius: 4px; cursor: pointer;';
    acceptBtn.addEventListener('click', () => {
      resolveMedicationReview(review.id, 'accept', canonicalInput.value.trim());
    });
    actions.appendChild(acceptBtn);

    const rejectBtn = document.createElement('button');
    rejectBtn.textContent = 'Reject';
    rejectBtn.style.cssText = 'background: #dc3545; color: white; border: none; padding: 7px 10px; border-radius: 4px; cursor: pointer;';
    rejectBtn.addEventListener('click', () => {
      resolveMedicationReview(review.id, 'reject', '');
    });
    actions.appendChild(rejectBtn);

    const dismissBtn = document.createElement('button');
    dismissBtn.textContent = 'Dismiss';
    dismissBtn.style.cssText = 'background: #6c757d; color: white; border: none; padding: 7px 10px; border-radius: 4px; cursor: pointer;';
    dismissBtn.addEventListener('click', () => {
      resolveMedicationReview(review.id, 'dismiss', '');
    });
    actions.appendChild(dismissBtn);

    item.appendChild(actions);
    medicationReviewList.appendChild(item);
  });
}

async function resolveMedicationReview(reviewId, action, canonicalOverride = '') {
  if (!reviewId || !action) {
    return;
  }
  if (action === 'accept' && !canonicalOverride) {
    setVocabularyStatus('Provide a canonical medication name before accepting.', { isError: true });
    return;
  }
  try {
    const result = await window.settingsAPI.callVocabularyAPI('resolve_medication_review', {
      review_id: reviewId,
      action,
      canonical_override: canonicalOverride
    });
    if (!result || result.success === false) {
      throw new Error(result?.error || 'Failed to resolve review item.');
    }
    setVocabularyStatus(result.message || 'Review item updated.');
    await loadVocabularyData();
  } catch (error) {
    setVocabularyStatus(error?.message || 'Failed to resolve review item.', { isError: true });
  }
}

async function loadVocabularyData() {
  try {
    const [mappingsResult, reviewResult, autoLearnResult] = await Promise.all([
      window.settingsAPI.callVocabularyAPI('get_medication_mappings'),
      window.settingsAPI.callVocabularyAPI('get_medication_review_queue', { status: 'pending' }),
      window.settingsAPI.callVocabularyAPI('get_medication_autolearn_status')
    ]);

    if (!mappingsResult || mappingsResult.success === false) {
      throw new Error(mappingsResult?.error || 'Unable to load medication mappings.');
    }
    currentMedicationMappings = Array.isArray(mappingsResult.mappings) ? mappingsResult.mappings : [];

    if (!reviewResult || reviewResult.success === false) {
      throw new Error(reviewResult?.error || 'Unable to load review queue.');
    }
    currentMedicationReviews = Array.isArray(reviewResult.reviews) ? reviewResult.reviews : [];

    if (autoLearnResult && autoLearnResult.success !== false) {
      const statusPayload = autoLearnResult.status || {};
      if (medicationAutoLearnToggle && typeof statusPayload.enabled === 'boolean') {
        medicationAutoLearnToggle.checked = !!statusPayload.enabled;
      }
      renderMedicationAutoLearnSummary(statusPayload.lastSummary || autoLearnResult.lastSummary);
    } else {
      renderMedicationAutoLearnSummary(null);
    }

    renderMedicationStats();
    renderMedicationMappings();
    renderMedicationReviewQueue();
  } catch (error) {
    console.error('Failed to load medication vocabulary data:', error);
    setVocabularyStatus(error?.message || 'Error loading medication vocabulary data.', { isError: true, timeoutMs: 0 });
    currentMedicationMappings = [];
    currentMedicationReviews = [];
    renderMedicationAutoLearnSummary(null);
    updateVocabularyNavBadge(0);
    renderMedicationStats();
    renderMedicationMappings();
    renderMedicationReviewQueue();
  }
}

async function addMedicationMappingFromForm() {
  const observed = medicationObservedInput?.value.trim() || '';
  const canonical = medicationCanonicalInput?.value.trim() || '';
  if (!observed || !canonical) {
    setVocabularyStatus('Both observed phrase and canonical medication name are required.', { isError: true });
    return;
  }
  try {
    const result = await window.settingsAPI.callVocabularyAPI('add_medication_mapping', {
      observed,
      canonical,
      source: 'settings_manual',
      confidence: 'manual'
    });
    if (!result || result.success === false) {
      throw new Error(result?.error || 'Failed to save medication mapping.');
    }
    medicationObservedInput.value = '';
    medicationCanonicalInput.value = '';
    setVocabularyStatus(result.message || 'Medication mapping saved.');
    await loadVocabularyData();
  } catch (error) {
    setVocabularyStatus(error?.message || 'Failed to save medication mapping.', { isError: true });
  }
}

async function importMedicationReport() {
  const reportPath = medicationReportPathInput?.value.trim() || '';
  if (!reportPath) {
    setVocabularyStatus('Provide a report path to import.', { isError: true });
    return;
  }
  try {
    const result = await window.settingsAPI.callVocabularyAPI('import_medication_report', {
      report_path: reportPath,
      min_confidence: 'medium',
      auto_import_confidence: 'high',
      min_occurrence_count: 1,
      min_entry_count: 1
    });
    if (!result || result.success === false) {
      throw new Error(result?.error || 'Failed to import medication report.');
    }
    setVocabularyStatus(result.message || 'Medication report imported.');
    await loadVocabularyData();
  } catch (error) {
    setVocabularyStatus(error?.message || 'Failed to import medication report.', { isError: true, timeoutMs: 6000 });
  }
}

async function persistMedicationAutoLearnSetting(enabled) {
  try {
    window.settingsAPI.saveSettings({ medicationAutoLearnEnabled: !!enabled });
    setVocabularyStatus(`Medication auto-learn ${enabled ? 'enabled' : 'disabled'}.`, { timeoutMs: 2000 });
    await loadVocabularyData();
  } catch (error) {
    setVocabularyStatus(error?.message || 'Failed to save medication auto-learn setting.', { isError: true });
  }
}

async function runMedicationAutoLearnNow() {
  if (!medicationAutoLearnRunNowButton) {
    return;
  }
  medicationAutoLearnRunNowButton.disabled = true;
  try {
    const result = await window.settingsAPI.callVocabularyAPI('run_medication_autolearn_now');
    if (!result || result.success === false) {
      throw new Error(result?.error || 'Failed to run medication auto-learn.');
    }
    renderMedicationAutoLearnSummary(result.summary || result.status?.lastSummary);
    setVocabularyStatus('Medication auto-learn run completed.');
    await loadVocabularyData();
  } catch (error) {
    setVocabularyStatus(error?.message || 'Medication auto-learn run failed.', { isError: true });
  } finally {
    medicationAutoLearnRunNowButton.disabled = false;
  }
}

if (medicationAddButton) {
  medicationAddButton.addEventListener('click', addMedicationMappingFromForm);
}
if (medicationCanonicalInput) {
  medicationCanonicalInput.addEventListener('keypress', (event) => {
    if (event.key === 'Enter') {
      addMedicationMappingFromForm();
    }
  });
}
if (medicationSearchInput) {
  medicationSearchInput.addEventListener('input', renderMedicationMappings);
}
if (medicationImportButton) {
  medicationImportButton.addEventListener('click', importMedicationReport);
}
if (medicationAutoLearnToggle) {
  medicationAutoLearnToggle.addEventListener('change', () => {
    persistMedicationAutoLearnSetting(!!medicationAutoLearnToggle.checked);
  });
}
if (medicationAutoLearnRunNowButton) {
  medicationAutoLearnRunNowButton.addEventListener('click', runMedicationAutoLearnNow);
}

// --- Cloud API Settings (masked key management) ---
const settingsOpenaiStatus = document.getElementById('settings-openai-status');
const settingsOpenaiAdd = document.getElementById('settings-openai-add');
const settingsOpenaiDelete = document.getElementById('settings-openai-delete');
const settingsOpenaiEntry = document.getElementById('settings-openai-entry');
const settingsOpenaiInput = document.getElementById('settings-openai-input');
const settingsOpenaiSave = document.getElementById('settings-openai-save');
const settingsOpenaiCancel = document.getElementById('settings-openai-cancel');
const settingsGoogleStatus = document.getElementById('settings-google-status');
const settingsGoogleAdd = document.getElementById('settings-google-add');
const settingsGoogleDelete = document.getElementById('settings-google-delete');
// cloudapi-status element available if needed for future feedback

async function refreshSettingsApiKeyStatus() {
  try {
    const status = await window.settingsAPI.getApiKeyStatus();
    if (settingsOpenaiStatus) {
      if (status.openai.configured) {
        settingsOpenaiStatus.textContent = status.openai.masked;
        settingsOpenaiStatus.style.color = '#4dd37a';
        if (settingsOpenaiAdd) settingsOpenaiAdd.textContent = 'Change';
        if (settingsOpenaiDelete) settingsOpenaiDelete.style.display = '';
      } else {
        settingsOpenaiStatus.textContent = 'Not configured';
        settingsOpenaiStatus.style.color = '#888';
        if (settingsOpenaiAdd) settingsOpenaiAdd.textContent = 'Add Key';
        if (settingsOpenaiDelete) settingsOpenaiDelete.style.display = 'none';
      }
    }
    if (settingsGoogleStatus) {
      if (status.google.configured) {
        settingsGoogleStatus.textContent = status.google.masked;
        settingsGoogleStatus.style.color = '#4dd37a';
        if (settingsGoogleAdd) settingsGoogleAdd.textContent = 'Change';
        if (settingsGoogleDelete) settingsGoogleDelete.style.display = '';
      } else {
        settingsGoogleStatus.textContent = 'Not configured';
        settingsGoogleStatus.style.color = '#888';
        if (settingsGoogleAdd) settingsGoogleAdd.textContent = 'Add Key';
        if (settingsGoogleDelete) settingsGoogleDelete.style.display = 'none';
      }
    }
  } catch (err) {
    console.warn('Failed to load API key status:', err);
  }
}

if (settingsOpenaiAdd) {
  settingsOpenaiAdd.addEventListener('click', () => {
    if (settingsOpenaiEntry) settingsOpenaiEntry.style.display = '';
    if (settingsOpenaiInput) { settingsOpenaiInput.value = ''; settingsOpenaiInput.focus(); }
  });
}
if (settingsOpenaiCancel) {
  settingsOpenaiCancel.addEventListener('click', () => {
    if (settingsOpenaiEntry) settingsOpenaiEntry.style.display = 'none';
  });
}
if (settingsOpenaiSave) {
  settingsOpenaiSave.addEventListener('click', async () => {
    const val = settingsOpenaiInput ? settingsOpenaiInput.value.trim() : '';
    if (!val) return;
    await window.settingsAPI.saveApiKey('openai', val);
    if (settingsOpenaiEntry) settingsOpenaiEntry.style.display = 'none';
    refreshSettingsApiKeyStatus();
  });
}
if (settingsOpenaiDelete) {
  settingsOpenaiDelete.addEventListener('click', async () => {
    await window.settingsAPI.deleteApiKey('openai');
    refreshSettingsApiKeyStatus();
  });
}
if (settingsGoogleAdd) {
  settingsGoogleAdd.addEventListener('click', () => {
    // Inline entry for Google API key (reuse the OpenAI pattern)
    const input = prompt('Enter your Google AI API Key:');
    if (input && input.trim()) {
      window.settingsAPI.saveApiKey('google', input.trim()).then(() => {
        refreshSettingsApiKeyStatus();
      });
    }
  });
}
if (settingsGoogleDelete) {
  settingsGoogleDelete.addEventListener('click', async () => {
    await window.settingsAPI.deleteApiKey('google');
    refreshSettingsApiKeyStatus();
  });
}

// --- Initialization ---
window.addEventListener('DOMContentLoaded', () => {
  initializeShortcutControls();
  initializeMicrophoneControls();
  renderShortcutButtons();
  loadAndPopulateSettings();
  loadVocabularyData(); // Load vocabulary data
  showSection('wakewords'); // Show the first section by default

  // Listen for navigation requests from main process (e.g., direct vocabulary access)
  window.settingsAPI.onNavigateToSection((event, section) => {
    if (section === 'vocabulary') {
      console.log('Navigating to vocabulary section via tray menu');
      showSection('vocabulary'); // Use 'vocabulary' not 'section-vocabulary'
      // The showSection function already handles sidebar activation, but let's be explicit
      setTimeout(() => {
        console.log('Loading vocabulary data after navigation...');
        loadVocabularyData();
      }, 100);
    }
  });
});

window.addEventListener('beforeunload', () => {
  if (backendHotkeysSuspended || activeShortcutCapture) {
    void setBackendHotkeysSuspended(false);
  }
});
