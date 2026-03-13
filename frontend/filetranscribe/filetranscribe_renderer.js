// File Transcription renderer logic

// View navigation
const navHomeBtn = document.getElementById('nav-home-btn');
const navLdBtn = document.getElementById('nav-ld-btn');
if (navHomeBtn && window.navAPI) {
  navHomeBtn.addEventListener('click', () => window.navAPI.goHome());
}
if (navLdBtn && window.navAPI) {
  navLdBtn.addEventListener('click', () => window.navAPI.goLiveDictation());
}

let selectedFilePath = null;
let isTranscribing = false;
let cleanupProgress = null;
let cleanupResult = null;

// DOM Elements
const pickFileButton = document.getElementById('ft-pick-file');
const fileNameLabel = document.getElementById('ft-file-name');
const clearFileButton = document.getElementById('ft-clear-file');
const backendSelect = document.getElementById('ft-backend-select');
const languageSelect = document.getElementById('ft-language-select');
const diarizationToggle = document.getElementById('ft-diarization-toggle');
const transcribeButton = document.getElementById('ft-transcribe-button');
const progressSection = document.getElementById('ft-progress');
const progressLabel = document.getElementById('ft-progress-label');
const progressBar = document.getElementById('ft-progress-bar');
const resultSection = document.getElementById('ft-result');
const transcriptDiv = document.getElementById('ft-transcript');
const actionsFooter = document.getElementById('ft-actions');
const copyButton = document.getElementById('ft-copy-button');
const saveButton = document.getElementById('ft-save-button');
const errorMessage = document.getElementById('ft-error');

// API Key Elements
const apikeyOpenaiStatus = document.getElementById('apikey-openai-status');
const apikeyGoogleStatus = document.getElementById('apikey-google-status');
const apikeyOpenaiAdd = document.getElementById('apikey-openai-add');
const apikeyOpenaiDelete = document.getElementById('apikey-openai-delete');
const apikeyGoogleAdd = document.getElementById('apikey-google-add');
const apikeyGoogleDelete = document.getElementById('apikey-google-delete');
const apikeyEntryPanel = document.getElementById('apikey-entry-panel');
const apikeyEntryLabel = document.getElementById('apikey-entry-label');
const apikeyEntryInput = document.getElementById('apikey-entry-input');
const apikeyEntrySave = document.getElementById('apikey-entry-save');
const apikeyEntryCancel = document.getElementById('apikey-entry-cancel');

let activeKeyProvider = null; // 'openai' or 'google'

// --- API Key Management ---

async function refreshApiKeyStatus() {
  try {
    const status = await window.fileTranscribeAPI.getApiKeyStatus();

    if (status.openai.configured) {
      apikeyOpenaiStatus.textContent = status.openai.masked;
      apikeyOpenaiStatus.classList.remove('not-configured');
      apikeyOpenaiStatus.classList.add('configured');
      apikeyOpenaiAdd.textContent = 'Change';
      apikeyOpenaiDelete.classList.remove('hidden');
    } else {
      apikeyOpenaiStatus.textContent = 'Not configured';
      apikeyOpenaiStatus.classList.add('not-configured');
      apikeyOpenaiStatus.classList.remove('configured');
      apikeyOpenaiAdd.textContent = 'Add Key';
      apikeyOpenaiDelete.classList.add('hidden');
    }

    if (status.google.configured) {
      apikeyGoogleStatus.textContent = status.google.masked;
      apikeyGoogleStatus.classList.remove('not-configured');
      apikeyGoogleStatus.classList.add('configured');
      apikeyGoogleAdd.textContent = 'Change';
      apikeyGoogleDelete.classList.remove('hidden');
    } else {
      apikeyGoogleStatus.textContent = 'Not configured';
      apikeyGoogleStatus.classList.add('not-configured');
      apikeyGoogleStatus.classList.remove('configured');
      apikeyGoogleAdd.textContent = 'Add Key';
      apikeyGoogleDelete.classList.add('hidden');
    }
  } catch (err) {
    console.warn('Failed to load API key status:', err);
  }
}

function showKeyEntryPanel(provider) {
  activeKeyProvider = provider;
  apikeyEntryPanel.classList.remove('hidden');
  apikeyEntryInput.value = '';
  apikeyEntryInput.focus();

  if (provider === 'openai') {
    apikeyEntryLabel.textContent = 'OpenAI API Key';
    apikeyEntryInput.placeholder = 'sk-...';
    apikeyEntryInput.type = 'password';
  } else if (provider === 'google') {
    apikeyEntryLabel.textContent = 'Google AI API Key';
    apikeyEntryInput.placeholder = 'AIza...';
    apikeyEntryInput.type = 'password';
  }
}

function hideKeyEntryPanel() {
  activeKeyProvider = null;
  apikeyEntryPanel.classList.add('hidden');
  apikeyEntryInput.value = '';
}

apikeyOpenaiAdd.addEventListener('click', () => {
  showKeyEntryPanel('openai');
});

apikeyGoogleAdd.addEventListener('click', () => {
  showKeyEntryPanel('google');
});

apikeyOpenaiDelete.addEventListener('click', async () => {
  try {
    await window.fileTranscribeAPI.deleteApiKey('openai');
    await refreshApiKeyStatus();
  } catch (err) {
    showError('Failed to remove key: ' + (err.message || err));
  }
});

apikeyGoogleDelete.addEventListener('click', async () => {
  try {
    await window.fileTranscribeAPI.deleteApiKey('google');
    await refreshApiKeyStatus();
  } catch (err) {
    showError('Failed to remove key: ' + (err.message || err));
  }
});

apikeyEntrySave.addEventListener('click', async () => {
  const value = apikeyEntryInput.value.trim();
  if (!value || !activeKeyProvider) return;

  try {
    await window.fileTranscribeAPI.saveApiKey(activeKeyProvider, value);
    hideKeyEntryPanel();
    await refreshApiKeyStatus();
  } catch (err) {
    showError('Failed to save key: ' + (err.message || err));
  }
});

apikeyEntryCancel.addEventListener('click', () => {
  hideKeyEntryPanel();
});

apikeyEntryInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') apikeyEntrySave.click();
  if (e.key === 'Escape') hideKeyEntryPanel();
});

// --- File Selection ---

pickFileButton.addEventListener('click', async () => {
  try {
    const result = await window.fileTranscribeAPI.pickFiles();
    if (result && result.filePath) {
      selectedFilePath = result.filePath;
      fileNameLabel.textContent = result.fileName || result.filePath.split(/[/\\]/).pop();
      fileNameLabel.classList.add('active');
      clearFileButton.classList.remove('hidden');
      transcribeButton.disabled = false;
      hideError();
    }
  } catch (err) {
    showError('Failed to select file: ' + (err.message || err));
  }
});

clearFileButton.addEventListener('click', () => {
  selectedFilePath = null;
  fileNameLabel.textContent = 'No file selected';
  fileNameLabel.classList.remove('active');
  clearFileButton.classList.add('hidden');
  transcribeButton.disabled = true;
  resultSection.classList.add('hidden');
  actionsFooter.classList.add('hidden');
  progressSection.classList.add('hidden');
  hideError();
});

// --- Transcription ---

transcribeButton.addEventListener('click', async () => {
  if (!selectedFilePath || isTranscribing) return;

  isTranscribing = true;
  transcribeButton.disabled = true;
  transcribeButton.textContent = 'Transcribing...';
  resultSection.classList.add('hidden');
  actionsFooter.classList.add('hidden');
  hideError();

  // Show progress
  progressSection.classList.remove('hidden');
  progressLabel.textContent = 'Starting...';
  progressBar.style.width = '0%';

  // Register progress/result listeners
  if (cleanupProgress) cleanupProgress();
  if (cleanupResult) cleanupResult();

  cleanupProgress = window.fileTranscribeAPI.onProgress((data) => {
    if (data && data.stage) {
      progressLabel.textContent = data.stage;
    }
    if (data && typeof data.percent === 'number') {
      progressBar.style.width = Math.min(100, data.percent) + '%';
    }
  });

  cleanupResult = window.fileTranscribeAPI.onResult((data) => {
    isTranscribing = false;
    transcribeButton.disabled = false;
    transcribeButton.textContent = 'Transcribe';
    progressSection.classList.add('hidden');

    if (data && data.success) {
      const text = data.diarizationEnabled && data.diarizedText
        ? data.diarizedText
        : data.fullText || '';
      transcriptDiv.textContent = text;
      resultSection.classList.remove('hidden');
      actionsFooter.classList.remove('hidden');
    } else {
      showError(data?.error || 'Transcription failed.');
    }
  });

  try {
    const opts = {
      filePath: selectedFilePath,
      modelId: backendSelect.value,
      diarization: diarizationToggle.checked,
      language: languageSelect.value
    };
    await window.fileTranscribeAPI.transcribe(opts);
  } catch (err) {
    isTranscribing = false;
    transcribeButton.disabled = false;
    transcribeButton.textContent = 'Transcribe';
    progressSection.classList.add('hidden');
    showError('Transcription request failed: ' + (err.message || err));
  }
});

// --- Export ---

copyButton.addEventListener('click', () => {
  const text = transcriptDiv.textContent || '';
  window.fileTranscribeAPI.copyText(text);
  copyButton.textContent = 'Copied!';
  setTimeout(() => { copyButton.textContent = 'Copy to Clipboard'; }, 2000);
});

saveButton.addEventListener('click', async () => {
  const text = transcriptDiv.textContent || '';
  const fileName = fileNameLabel.textContent.replace(/\.[^.]+$/, '') || 'transcript';
  try {
    const result = await window.fileTranscribeAPI.exportText(text, 'txt', fileName + '.txt');
    if (result && result.success) {
      saveButton.textContent = 'Saved!';
      setTimeout(() => { saveButton.textContent = 'Save as .txt'; }, 2000);
    }
  } catch (err) {
    showError('Failed to save file: ' + (err.message || err));
  }
});

// --- Helpers ---

function showError(msg) {
  errorMessage.textContent = msg;
  errorMessage.classList.remove('hidden');
}

function hideError() {
  errorMessage.textContent = '';
  errorMessage.classList.add('hidden');
}

// --- Diarization hint ---
backendSelect.addEventListener('change', () => {
  const isGoogle = backendSelect.value.startsWith('google:');
  diarizationToggle.disabled = !isGoogle;
  if (!isGoogle) {
    diarizationToggle.checked = false;
  }
});

// Initialize
diarizationToggle.disabled = !backendSelect.value.startsWith('google:');
refreshApiKeyStatus();
