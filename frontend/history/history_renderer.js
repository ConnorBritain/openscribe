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

  if (entry.audioFileUrl) {
    audioSection.classList.remove('hidden');
    audioPlayer.src = entry.audioFileUrl;
    audioHint.textContent = '';
  } else {
    audioSection.classList.add('hidden');
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

loadHistory().catch((error) => {
  console.error('Failed to load history', error);
});
