const listContainer = document.getElementById('history-list');
const searchInput = document.getElementById('history-search');
const detailContainer = document.getElementById('history-detail-content');
const emptyDetail = document.getElementById('history-detail-empty');
const detailTitle = document.getElementById('detail-title');
const detailMeta = document.getElementById('detail-meta');
const copyButton = document.getElementById('detail-copy-button');
const audioSection = document.getElementById('detail-audio-section');
const audioPlayer = document.getElementById('detail-audio-player');
const audioHint = document.getElementById('detail-audio-hint');
const transcriptContainer = document.getElementById('detail-transcript');
const correctionToolbar = document.getElementById('correction-toolbar');
const correctionSelection = document.getElementById('correction-selection');
const correctionInput = document.getElementById('correction-input');
const correctionButton = document.getElementById('correction-learn');
const deleteButton = document.getElementById('detail-delete-button');
const detailFeedback = document.getElementById('detail-feedback');

// Comparison UI Elements
const compareButton = document.getElementById('detail-compare-button');
const compareControls = document.getElementById('compare-controls');
const compareModelSelect = document.getElementById('compare-model-select');
const compareCancelButton = document.getElementById('compare-cancel-button');
const comparisonView = document.getElementById('comparison-view');
const comparisonOriginalText = document.getElementById('comparison-original-text');
const comparisonNewText = document.getElementById('comparison-new-text');
const comparisonNewTitle = document.getElementById('comparison-new-title');

let historyEntries = [];
let filteredEntries = [];
let selectedEntryId = null;
let selectedEntry = null;

function formatDate(isoString) {
  if (!isoString) return 'Unknown time';
  try {
    const date = new Date(isoString);
    return date.toLocaleString();
  } catch (error) {
    return isoString;
  }
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return '';
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  }
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m ${secs.toString().padStart(2, '0')}s`;
}

function renderList() {
  listContainer.innerHTML = '';
  if (!filteredEntries.length) {
    const emptyDiv = document.createElement('div');
    emptyDiv.className = 'empty-state';
    emptyDiv.textContent = historyEntries.length ? 'No matches found.' : 'No history yet. Dictations will appear here.';
    listContainer.appendChild(emptyDiv);
    return;
  }

  filteredEntries.forEach((entry) => {
    const button = document.createElement('button');
    button.className = 'history-item';
    if (entry.id === selectedEntryId) {
      button.classList.add('active');
    }
    button.dataset.entryId = entry.id;

    const title = document.createElement('h3');
    title.textContent = formatDate(entry.createdAt);
    button.appendChild(title);

    const meta = document.createElement('p');
    const duration = formatDuration(entry.durationSeconds);
    const model = entry.metadata?.model ? ` • ${entry.metadata.model}` : '';
    meta.textContent = `${duration || '—'}${model}`;
    button.appendChild(meta);

    if (entry.transcriptPreview) {
      const preview = document.createElement('p');
      preview.className = 'history-item__preview';
      const previewText = entry.transcriptPreview.length > 140
        ? `${entry.transcriptPreview.slice(0, 137)}…`
        : entry.transcriptPreview;
      preview.textContent = previewText || '—';
      button.appendChild(preview);
    }

    button.addEventListener('click', () => selectEntry(entry.id));
    listContainer.appendChild(button);
  });
}

async function loadHistory() {
  historyEntries = await window.historyAPI.getList();
  filteredEntries = [...historyEntries];
  renderList();
  if (filteredEntries.length) {
    selectEntry(filteredEntries[0].id);
  }
}

async function selectEntry(entryId) {
  if (!entryId) return;
  selectedEntryId = entryId;
  listContainer.querySelectorAll('.history-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.entryId === entryId);
  });

  const entry = await window.historyAPI.getEntry(entryId);
  if (!entry) {
    showEmptyDetail();
    return;
  }
  selectedEntry = entry;
  renderDetail(entry);
}

function showEmptyDetail() {
  detailContainer.classList.add('hidden');
  emptyDetail.classList.remove('hidden');
  if (detailFeedback) {
    detailFeedback.textContent = '';
    detailFeedback.style.color = '';
  }
  if (deleteButton) deleteButton.disabled = true;
}

function renderDetail(entry) {
  detailContainer.classList.remove('hidden');
  emptyDetail.classList.add('hidden');
  correctionToolbar.classList.add('hidden');
  if (detailFeedback) {
    detailFeedback.textContent = '';
    detailFeedback.style.color = '';
  }
  if (deleteButton) deleteButton.disabled = false;

  detailTitle.textContent = formatDate(entry.createdAt);
  const durationText = formatDuration(entry.durationSeconds);
  const model = entry.metadata?.model ? ` • ${entry.metadata.model}` : '';
  detailMeta.textContent = `${durationText || 'Duration unknown'}${model}`;

  const transcriptText = entry.processedTranscript || entry.transcript || '';
  transcriptContainer.textContent = transcriptText;

  // Reset comparison view
  compareControls.classList.add('hidden');
  comparisonView.classList.add('hidden');
  transcriptContainer.classList.remove('hidden-for-compare');

  if (entry.audioFileUrl) {
    audioSection.classList.remove('hidden');
    compareButton.classList.remove('hidden');
    audioPlayer.src = entry.audioFileUrl;
    audioHint.textContent = '';
  } else {
    audioSection.classList.add('hidden');
    compareButton.classList.add('hidden');
    audioPlayer.removeAttribute('src');
    audioPlayer.load();
  }
}

function handleSearch(event) {
  const query = event.target.value.trim().toLowerCase();
  const previousSelectedIndex = filteredEntries.findIndex((entry) => entry.id === selectedEntryId);
  if (!query) {
    filteredEntries = [...historyEntries];
  } else {
    filteredEntries = historyEntries.filter((entry) => {
      const haystack = [
        entry.transcriptPreview || '',
        entry.metadata?.model || '',
        entry.createdAt || ''
      ].join(' ').toLowerCase();
      return haystack.includes(query);
    });
  }
  renderList();
  if (!filteredEntries.some((entry) => entry.id === selectedEntryId)) {
    if (filteredEntries.length) {
      const fallbackIndex = previousSelectedIndex >= 0
        ? Math.min(previousSelectedIndex, filteredEntries.length - 1)
        : 0;
      selectEntry(filteredEntries[fallbackIndex].id);
    } else {
      selectedEntryId = null;
      selectedEntry = null;
      showEmptyDetail();
    }
  }
}

function getSelectionTextWithinTranscript() {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return '';
  const range = selection.getRangeAt(0);
  if (!transcriptContainer.contains(range.commonAncestorContainer)) {
    return '';
  }
  const text = selection.toString().trim();
  return text;
}

function updateCorrectionToolbar() {
  const selectedText = getSelectionTextWithinTranscript();
  if (!selectedText) {
    correctionToolbar.classList.add('hidden');
    if (correctionButton) correctionButton.disabled = true;
    return;
  }
  correctionSelection.textContent = selectedText.length > 80 ? `${selectedText.slice(0, 77)}…` : selectedText;
  correctionToolbar.classList.remove('hidden');
  if (correctionInput) {
    correctionInput.value = selectedText;
    correctionInput.focus();
    correctionInput.select();
  }
  if (correctionButton) correctionButton.disabled = false;
}

async function learnCorrection() {
  const original = getSelectionTextWithinTranscript();
  if (!original) {
    correctionToolbar.classList.add('hidden');
    return;
  }
  const corrected = correctionInput?.value.trim();
  if (!corrected) {
    alert('Enter the corrected wording first.');
    correctionInput?.focus();
    return;
  }

  try {
    await window.historyAPI.learnCorrection({
      original,
      corrected,
      context: selectedEntry?.processedTranscript || selectedEntry?.transcript || ''
    });
    correctionToolbar.classList.add('hidden');
    if (correctionInput) correctionInput.value = '';
    if (correctionButton) correctionButton.disabled = true;
    alert('Correction saved to vocabulary.');
  } catch (error) {
    console.error('Failed to learn correction', error);
    alert('Failed to save correction.');
  }
}

function copyTranscript() {
  if (!selectedEntry) return;
  const text = selectedEntry.processedTranscript || selectedEntry.transcript || '';
  window.historyAPI.copyText(text);
}

searchInput.addEventListener('input', handleSearch);
transcriptContainer.addEventListener('mouseup', updateCorrectionToolbar);
transcriptContainer.addEventListener('keyup', updateCorrectionToolbar);
correctionButton.addEventListener('click', learnCorrection);
correctionInput?.addEventListener('keypress', (event) => {
  if (event.key === 'Enter') {
    learnCorrection();
  }
});
copyButton.addEventListener('click', copyTranscript);

deleteButton?.addEventListener('click', async () => {
  if (!selectedEntryId) {
    return;
  }

  const entryId = selectedEntryId;
  const currentIndex = filteredEntries.findIndex((entry) => entry.id === entryId);
  if (detailFeedback) {
    detailFeedback.textContent = 'Deleting entry…';
    detailFeedback.style.color = '#ffb400';
  }
  deleteButton.disabled = true;

  try {
    const result = await window.historyAPI.deleteEntry(entryId);
    if (!result || result.success === false) {
      const errMessage = result?.error || 'Failed to delete entry.';
      throw new Error(errMessage);
    }

    historyEntries = historyEntries.filter((entry) => entry.id !== entryId);
    filteredEntries = filteredEntries.filter((entry) => entry.id !== entryId);
    selectedEntryId = null;
    selectedEntry = null;

    renderList();

    if (filteredEntries.length) {
      const nextIndex = currentIndex >= 0 ? Math.min(currentIndex, filteredEntries.length - 1) : 0;
      selectEntry(filteredEntries[nextIndex].id);
    } else {
      showEmptyDetail();
    }

    if (detailFeedback) {
      detailFeedback.textContent = 'Entry deleted.';
      detailFeedback.style.color = '#6be07a';
    }
  } catch (error) {
    console.error('Failed to delete history entry', error);
    if (detailFeedback) {
      detailFeedback.textContent = `Failed to delete entry: ${error?.message || error}`;
      detailFeedback.style.color = '#ff6b6b';
    }
  } finally {
    deleteButton.disabled = false;
  }
});

// Comparison Feature Logic

async function loadModels() {
  try {
    const models = await window.historyAPI.getAsrModels();

    // Save current selection if any
    const currentVal = compareModelSelect.value;

    compareModelSelect.innerHTML = '<option value="" disabled selected>Select model to compare...</option>';

    let modelEntries = [];
    if (Array.isArray(models)) {
      // If array of strings or objects
      modelEntries = models.map(m => typeof m === 'string' ? { id: m, name: m } : m);
    } else if (models && typeof models === 'object') {
      // Config dict: { "Friendly Name": "model_id" }
      modelEntries = Object.entries(models).map(([name, id]) => ({ id, name }));
    }

    modelEntries.forEach(model => {
      const option = document.createElement('option');
      option.value = model.id;
      option.textContent = model.name;
      compareModelSelect.appendChild(option);
    });

    if (currentVal) {
      compareModelSelect.value = currentVal;
    }
  } catch (e) {
    console.error('Failed to load models:', e);
  }
}

function showComparisonControls() {
  compareControls.classList.remove('hidden');
  compareButton.classList.add('hidden'); // Hide the button while comparing
  loadModels();
}

function cancelComparison() {
  compareControls.classList.add('hidden');
  comparisonView.classList.add('hidden');
  transcriptContainer.classList.remove('hidden-for-compare');
  compareButton.classList.remove('hidden');
  compareModelSelect.value = "";

  if (detailFeedback) {
    detailFeedback.textContent = '';
    detailFeedback.style.color = '';
  }
}

async function handleReTranscribe() {
  const modelId = compareModelSelect.value;
  if (!modelId || !selectedEntryId) return;

  // UI Setup
  comparisonView.classList.remove('hidden');
  transcriptContainer.classList.add('hidden-for-compare');

  // Show original text
  const originalText = selectedEntry.processedTranscript || selectedEntry.transcript || '';
  comparisonOriginalText.textContent = originalText;

  // Show loading in new text
  comparisonNewTitle.textContent = "Re-transcribing...";
  comparisonNewText.innerHTML = '<div style="text-align:center; padding: 20px; color: #8cc4ff;"><i>Processing audio with new model...</i><br><small>This may take a moment to load the model.</small></div>';

  if (detailFeedback) {
    detailFeedback.textContent = `Re-transcribing with ${modelId}...`;
    detailFeedback.style.color = '#8cc4ff';
  }

  try {
    const result = await window.historyAPI.retranscribe(selectedEntryId, modelId);

    if (result.success) {
      comparisonNewTitle.textContent = `New Model (${result.duration}s)`;
      comparisonNewText.textContent = result.transcript;
      if (detailFeedback) detailFeedback.textContent = '';
    } else {
      comparisonNewText.textContent = `Error: ${result.error}`;
      if (detailFeedback) {
        detailFeedback.textContent = 'Re-transcription failed.';
        detailFeedback.style.color = '#ff6b6b';
      }
    }
  } catch (error) {
    console.error('Re-transcription failed:', error);
    comparisonNewText.textContent = `Error: ${error.message}`;
    if (detailFeedback) {
      detailFeedback.textContent = 'Re-transcription failed.';
      detailFeedback.style.color = '#ff6b6b';
    }
  }
}

// Event Listeners for Comparison
if (compareButton) compareButton.addEventListener('click', showComparisonControls);
if (compareCancelButton) compareCancelButton.addEventListener('click', cancelComparison);
if (compareModelSelect) compareModelSelect.addEventListener('change', handleReTranscribe);

loadHistory().catch((error) => {
  console.error('Failed to load history', error);
});
