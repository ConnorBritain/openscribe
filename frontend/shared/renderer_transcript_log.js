// renderer_transcript_log.js
// Manages the live transcript stream shown in the main renderer UI,
// including inline vocabulary correction shortcuts.

import { logMessage } from './renderer_utils.js';

const MAX_SELECTION_LENGTH = 140;

let transcriptContainer = null;
let transcripts = [];
let activeTranscriptId = null;
let sequenceCounter = 0;
let heightAdjustmentCallback = null;

// Runtime caches used for quick DOM updates without full re-render.
let entryDomMap = new Map();
let currentSelection = { entryId: null, text: '' };
let selectionHandlersRegistered = false;

const STATUS_LABELS = {
  listening: 'Listening…',
  recording: 'Recording…',
  processing: 'Processing…',
  complete: 'Complete',
  error: 'Needs attention'
};

function ensureContainer() {
  if (!transcriptContainer) {
    transcriptContainer = document.getElementById('transcript-stream');
    if (!transcriptContainer) {
      console.warn('[TranscriptLog] transcript-stream container missing in DOM');
    }
  }
  return transcriptContainer;
}

function formatTimestamp(date) {
  try {
    return new Intl.DateTimeFormat(undefined, {
      hour: 'numeric',
      minute: '2-digit'
    }).format(date);
  } catch (error) {
    return date.toLocaleTimeString();
  }
}

function truncateSelectionPreview(text) {
  if (!text) {
    return '';
  }
  return text.length > 80 ? `${text.slice(0, 77)}…` : text;
}

function createTranscriptToolbar(entryId) {
  const toolbar = document.createElement('div');
  toolbar.className = 'transcript-entry__toolbar is-hidden';
  toolbar.dataset.entryId = entryId;

  const selectionPreview = document.createElement('span');
  selectionPreview.className = 'transcript-entry__selection-preview';
  toolbar.appendChild(selectionPreview);

  const actions = document.createElement('div');
  actions.className = 'transcript-entry__toolbar-actions';
  toolbar.appendChild(actions);

  const learnInput = document.createElement('input');
  learnInput.type = 'text';
  learnInput.className = 'transcript-entry__learn-input';
  learnInput.placeholder = 'Enter corrected wording…';
  actions.appendChild(learnInput);

  const learnButton = document.createElement('button');
  learnButton.type = 'button';
  learnButton.className = 'transcript-entry__learn-button';
  learnButton.textContent = 'Save correction';
  learnButton.disabled = true;
  actions.appendChild(learnButton);

  const feedback = document.createElement('div');
  feedback.className = 'transcript-entry__toolbar-feedback';
  toolbar.appendChild(feedback);

  return { toolbar, learnButton, learnInput, selectionPreview, feedback };
}

function buildTranscriptEntry(entry) {
  const entryEl = document.createElement('article');
  entryEl.className = 'transcript-entry';
  entryEl.dataset.entryId = entry.id;

  const header = document.createElement('div');
  header.className = 'transcript-entry__header';
  entryEl.appendChild(header);

  const statusBadge = document.createElement('span');
  statusBadge.className = `transcript-entry__status transcript-entry__status--${entry.status}`;
  statusBadge.textContent = STATUS_LABELS[entry.status] || entry.status;
  header.appendChild(statusBadge);

  const timestampEl = document.createElement('span');
  timestampEl.className = 'transcript-entry__timestamp';
  timestampEl.textContent = formatTimestamp(entry.updatedAt || entry.createdAt);
  header.appendChild(timestampEl);

  const textBlock = document.createElement('div');
  textBlock.className = 'transcript-entry__text';
  textBlock.textContent = entry.text || (entry.status === 'recording' ? 'Capturing audio…' : '');
  entryEl.appendChild(textBlock);

  const metaFooter = document.createElement('div');
  metaFooter.className = 'transcript-entry__footer';
  metaFooter.textContent = entry.status === 'complete'
    ? 'Select text to teach the vocabulary what you meant.'
    : 'Latest dictation is shown here as it processes.';
  entryEl.appendChild(metaFooter);

  const { toolbar, learnButton, learnInput, selectionPreview, feedback } = createTranscriptToolbar(entry.id);
  entryEl.appendChild(toolbar);

  return {
    entryEl,
    textBlock,
    statusBadge,
    timestampEl,
    toolbar,
    learnButton,
    learnInput,
    selectionPreview,
    feedback
  };
}

function hideAllToolbars() {
  entryDomMap.forEach(({ toolbar, learnButton, learnInput, feedback }) => {
    if (toolbar) {
      toolbar.classList.add('is-hidden');
    }
    if (learnButton) {
      learnButton.disabled = true;
      learnButton.textContent = 'Save correction';
    }
    if (learnInput) {
      learnInput.value = '';
    }
    if (feedback) {
      feedback.textContent = '';
      feedback.classList.remove('is-error');
    }
  });
}

function renderTranscripts() {
  const container = ensureContainer();
  if (!container) {
    return;
  }

  container.innerHTML = '';
  entryDomMap = new Map();

  if (transcripts.length === 0) {
    const placeholder = document.createElement('div');
    placeholder.className = 'transcript-placeholder';
    placeholder.textContent = 'Dictation results will appear here once you start speaking.';
    container.appendChild(placeholder);
  } else {
    transcripts.forEach((entry) => {
      const {
        entryEl,
        textBlock,
        statusBadge,
        timestampEl,
        toolbar,
        learnButton,
        learnInput,
        selectionPreview,
        feedback
      } = buildTranscriptEntry(entry);

      container.appendChild(entryEl);

      entryDomMap.set(entry.id, {
        entryEl,
        textBlock,
        statusBadge,
        timestamp: timestampEl,
        toolbar,
        learnButton,
        learnInput,
        selectionPreview,
        feedback
      });

      learnButton.addEventListener('click', () => handleLearnButtonClick(entry.id));
      if (learnInput) {
        learnInput.addEventListener('keypress', (event) => {
          if (event.key === 'Enter') {
            handleLearnButtonClick(entry.id);
          }
        });
      }
    });
  }

  currentSelection = { entryId: null, text: '' };

  if (typeof heightAdjustmentCallback === 'function') {
    try {
      heightAdjustmentCallback();
    } catch (error) {
      console.warn('[TranscriptLog] Height adjustment callback failed:', error);
    }
  }
}

function findTranscriptById(id) {
  if (!id) {
    return null;
  }
  return transcripts.find((entry) => entry.id === id) || null;
}

function showToolbarForSelection(entryId, selectionText) {
  hideAllToolbars();

  const entryInfo = entryDomMap.get(entryId);
  if (!entryInfo) {
    return;
  }

  const transcriptData = findTranscriptById(entryId);
  if (!transcriptData || transcriptData.status !== 'complete') {
    entryInfo.toolbar.classList.remove('is-hidden');
    entryInfo.learnButton.disabled = true;
    if (entryInfo.selectionPreview) {
      entryInfo.selectionPreview.textContent = 'Corrections available after this note completes.';
    }
    if (entryInfo.feedback) {
      entryInfo.feedback.textContent = 'Wait for the dictation to finish before teaching corrections.';
      entryInfo.feedback.classList.remove('is-error');
    }
    currentSelection = { entryId: null, text: '' };
    return;
  }

  currentSelection = { entryId, text: selectionText };

  entryInfo.toolbar.classList.remove('is-hidden');
  entryInfo.learnButton.disabled = false;
  entryInfo.learnButton.textContent = 'Save correction';

  if (entryInfo.selectionPreview) {
    entryInfo.selectionPreview.textContent = `Selected: “${truncateSelectionPreview(selectionText)}”`;
  }

  if (entryInfo.feedback) {
    entryInfo.feedback.textContent = '';
    entryInfo.feedback.classList.remove('is-error');
  }

  if (entryInfo.learnInput) {
    entryInfo.learnInput.value = selectionText;
    entryInfo.learnInput.focus();
    entryInfo.learnInput.select();
  }

  if (selectionText.length > MAX_SELECTION_LENGTH) {
    entryInfo.learnButton.disabled = true;
    if (entryInfo.feedback) {
      entryInfo.feedback.textContent = 'Selection too long. Highlight up to 140 characters.';
      entryInfo.feedback.classList.add('is-error');
    }
  }
}

function clearSelectionState({ keepSelection = true } = {}) {
  currentSelection = { entryId: null, text: '' };
  hideAllToolbars();

  if (!keepSelection) {
    try {
      const selection = window.getSelection();
      if (selection && selection.removeAllRanges) {
        selection.removeAllRanges();
      }
    } catch (error) {
      // Ignore selection clearing errors
    }
  }
}

function replaceFirstOccurrence(source, search, replacement) {
  if (!source || !search) {
    return source;
  }
  const index = source.indexOf(search);
  if (index === -1) {
    return source;
  }
  return `${source.slice(0, index)}${replacement}${source.slice(index + search.length)}`;
}

function handleLearnButtonClick(entryId) {
  const selection = currentSelection;
  const entryInfo = entryDomMap.get(entryId);
  const transcript = findTranscriptById(entryId);

  if (!entryInfo || !transcript) {
    return;
  }

  if (!selection.text || selection.entryId !== entryId) {
    if (entryInfo.feedback) {
      entryInfo.feedback.textContent = 'Select the phrase you want to correct first.';
      entryInfo.feedback.classList.add('is-error');
    }
    return;
  }

  const originalText = selection.text;
  const input = entryInfo.learnInput;
  const corrected = input ? input.value.trim() : '';
  if (!corrected) {
    if (entryInfo.feedback) {
      entryInfo.feedback.textContent = 'Please enter the corrected wording.';
      entryInfo.feedback.classList.add('is-error');
    }
    if (input) input.focus();
    return;
  }

  const vocabularyApi = window.electronAPI && window.electronAPI.vocabularyApi;
  if (typeof vocabularyApi !== 'function') {
    if (entryInfo.feedback) {
      entryInfo.feedback.textContent = 'Vocabulary service unavailable in this build.';
      entryInfo.feedback.classList.add('is-error');
    }
    return;
  }

  entryInfo.learnButton.disabled = true;
  entryInfo.learnButton.textContent = 'Saving…';
  if (entryInfo.feedback) {
    entryInfo.feedback.textContent = '';
    entryInfo.feedback.classList.remove('is-error');
  }

  const payload = {
    original: originalText,
    corrected,
    context: transcript.text
  };

  vocabularyApi('learn_correction', payload)
    .then((result) => {
      const isFailure = result && result.success === false;
      if (isFailure) {
        const errorText = result?.error || 'Could not save correction.';
        if (entryInfo.feedback) {
          entryInfo.feedback.textContent = errorText;
          entryInfo.feedback.classList.add('is-error');
        }
        return;
      }

      const message = result?.message || 'Correction learned.';
      transcript.text = replaceFirstOccurrence(transcript.text, originalText, corrected);
      transcript.updatedAt = new Date();

      if (entryInfo.textBlock) {
        entryInfo.textBlock.textContent = transcript.text;
      }
      if (entryInfo.timestamp) {
        entryInfo.timestamp.textContent = formatTimestamp(transcript.updatedAt);
      }
      if (entryInfo.feedback) {
        entryInfo.feedback.textContent = message;
        entryInfo.feedback.classList.remove('is-error');
      }
      if (entryInfo.learnInput) {
        entryInfo.learnInput.value = '';
      }
      logMessage(`[TranscriptLog] Learned correction: "${originalText}" → "${corrected}"`);

      if (typeof heightAdjustmentCallback === 'function') {
        heightAdjustmentCallback();
      }

      setTimeout(() => clearSelectionState({ keepSelection: false }), 1200);
    })
    .catch((error) => {
      if (entryInfo.feedback) {
        entryInfo.feedback.textContent = error?.message || 'Failed to learn correction.';
        entryInfo.feedback.classList.add('is-error');
      }
    })
    .finally(() => {
      entryInfo.learnButton.disabled = false;
      entryInfo.learnButton.textContent = 'Save correction';
    });
}

function updateSelectionFromWindow() {
  try {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      clearSelectionState();
      return;
    }

    const rawText = selection.toString();
    const selectedText = rawText.replace(/\s+/g, ' ').trim();
    if (!selectedText) {
      clearSelectionState();
      return;
    }

    const range = selection.getRangeAt(0);
    let node = range.commonAncestorContainer;
    if (node.nodeType === Node.TEXT_NODE) {
      node = node.parentElement;
    }
    if (!(node instanceof Element)) {
      clearSelectionState();
      return;
    }

    const textElement = node.closest('.transcript-entry__text');
    if (!textElement) {
      clearSelectionState();
      return;
    }

    const entryElement = textElement.closest('.transcript-entry');
    if (!entryElement) {
      clearSelectionState();
      return;
    }

    const entryId = entryElement.dataset.entryId;
    if (!entryDomMap.has(entryId)) {
      clearSelectionState();
      return;
    }

    showToolbarForSelection(entryId, selectedText);
  } catch (error) {
    console.warn('[TranscriptLog] Unable to inspect selection:', error);
  }
}

function handleSelectionEvent() {
  // Allow the selection to settle before reading it.
  window.requestAnimationFrame(updateSelectionFromWindow);
}

function handleDocumentMouseDown(event) {
  const container = ensureContainer();
  if (!container) {
    return;
  }
  if (!container.contains(event.target)) {
    clearSelectionState();
  }
}

export function setTranscriptHeightCallback(callback) {
  heightAdjustmentCallback = callback;
}

export function initializeTranscriptLog() {
  const container = ensureContainer();
  if (!container) {
    return;
  }

  if (!selectionHandlersRegistered) {
    container.addEventListener('mouseup', handleSelectionEvent);
    container.addEventListener('keyup', handleSelectionEvent);
    container.addEventListener('touchend', handleSelectionEvent);
    document.addEventListener('mousedown', handleDocumentMouseDown);
    selectionHandlersRegistered = true;
  }

  renderTranscripts();
}

export function beginTranscriptSession() {
  const container = ensureContainer();
  if (!container) {
    return null;
  }

  const now = new Date();
  const entry = {
    id: `transcript-${Date.now()}-${++sequenceCounter}`,
    text: '',
    status: 'recording',
    createdAt: now,
    updatedAt: now
  };

  transcripts.unshift(entry);
  activeTranscriptId = entry.id;
  renderTranscripts();
  logMessage(`[TranscriptLog] Began new transcript session (${entry.id}).`);
  return entry.id;
}

export function updateActiveTranscriptStatus(status) {
  const entry = findTranscriptById(activeTranscriptId);
  if (!entry) {
    return;
  }
  entry.status = status;
  entry.updatedAt = new Date();
  renderTranscripts();
}

export function updateActiveTranscriptText(text, { finalize = false } = {}) {
  let entry = findTranscriptById(activeTranscriptId);
  if (!entry && transcripts.length === 0) {
    beginTranscriptSession();
    entry = findTranscriptById(activeTranscriptId);
  } else if (!entry) {
    entry = transcripts[0];
    activeTranscriptId = entry.id;
  }

  if (!entry) {
    logMessage('[TranscriptLog] Unable to update transcript text; no active entry.');
    return;
  }

  entry.text = text || '';
  entry.updatedAt = new Date();
  if (finalize) {
    entry.status = 'complete';
    activeTranscriptId = null;
  }
  renderTranscripts();
}

export function finalizeActiveTranscript(text) {
  updateActiveTranscriptText(text, { finalize: true });
}

export function resetTranscriptLog() {
  transcripts = [];
  activeTranscriptId = null;
  renderTranscripts();
}
