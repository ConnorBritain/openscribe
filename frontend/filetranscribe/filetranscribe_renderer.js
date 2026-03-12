// File Transcription renderer logic

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
      language: languageSelect.value,
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

// --- Settings-based model filtering ---

async function initializeBackendOptions() {
  try {
    const settings = await window.fileTranscribeAPI.getSettings();
    // Filter cloud models based on configured API keys
    // (API keys are stored in electron-store, not exposed to renderer)
    // For now, show all options - the backend will error clearly if key is missing
  } catch (err) {
    console.warn('Failed to load settings for file transcription:', err);
  }
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
initializeBackendOptions();
