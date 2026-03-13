// renderer_transcript_log.js
// Manages the live transcript stream shown in the main renderer UI,
// including copy/re-transcribe controls.

import { logMessage } from './renderer_utils.js';
import { ASR_MODELS, getModelName } from './asr_models.js';

let transcriptContainer = null;
let transcripts = [];
let activeTranscriptId = null;
let sequenceCounter = 0;
let heightAdjustmentCallback = null;
let lastHistoryEntryId = null;
let lastHistoryModel = null;
let pendingHistoryTranscriptId = null;

// Runtime caches used for quick DOM updates without full re-render.
let entryDomMap = new Map();

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

function createActionBar(entry) {
  const bar = document.createElement('div');
  bar.className = 'transcript-entry__action-bar';
  if (entry.status !== 'complete') {
    bar.classList.add('is-hidden');
  }

  const copyBtn = document.createElement('button');
  copyBtn.type = 'button';
  copyBtn.className = 'transcript-entry__action-btn';
  copyBtn.textContent = 'Copy';
  copyBtn.addEventListener('click', () => {
    const text = entry.text || '';
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).catch(() => { });
    }
    copyBtn.textContent = 'Copied!';
    setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
  });
  bar.appendChild(copyBtn);

  const retranscribeSelect = document.createElement('select');
  retranscribeSelect.className = 'transcript-entry__retranscribe-select';
  const defaultOpt = document.createElement('option');
  defaultOpt.value = '';
  defaultOpt.textContent = 'Re-transcribe \u25BE';
  defaultOpt.disabled = true;
  defaultOpt.selected = true;
  retranscribeSelect.appendChild(defaultOpt);

  ASR_MODELS.forEach((model) => {
    if (model.id === entry.historyModel) return;
    const opt = document.createElement('option');
    opt.value = model.id;
    opt.textContent = model.name;
    retranscribeSelect.appendChild(opt);
  });

  if (!entry.historyId) {
    retranscribeSelect.disabled = true;
    retranscribeSelect.title = 'No audio available for re-transcription';
  }

  retranscribeSelect.addEventListener('change', () => {
    const modelId = retranscribeSelect.value;
    if (!modelId || !entry.historyId) return;
    handleRetranscribeRequest(entry, modelId);
    retranscribeSelect.value = '';
  });

  bar.appendChild(retranscribeSelect);

  const retranscribeStatus = document.createElement('span');
  retranscribeStatus.className = 'transcript-entry__retranscribe-status';
  bar.appendChild(retranscribeStatus);

  return { actionBar: bar, retranscribeSelect, retranscribeStatus };
}

function handleRetranscribeRequest(entry, modelId) {
  const entryInfo = entryDomMap.get(entry.id);
  if (!entryInfo) return;

  const { retranscribeStatus, retranscribeSelect } = entryInfo;
  retranscribeSelect.disabled = true;
  retranscribeStatus.textContent = `Re-transcribing with ${getModelName(modelId)}...`;
  retranscribeStatus.className = 'transcript-entry__retranscribe-status';

  if (!entry.originalText) {
    entry.originalText = entry.text;
  }

  const retranscribeApi = window.electronAPI && window.electronAPI.retranscribe;
  if (typeof retranscribeApi !== 'function') {
    retranscribeStatus.textContent = 'Re-transcribe not available.';
    retranscribeStatus.classList.add('is-error');
    retranscribeSelect.disabled = false;
    return;
  }

  retranscribeApi(entry.historyId, modelId)
    .then((result) => {
      if (result && result.success) {
        entry.text = result.transcript;
        entry.historyModel = modelId;
        entry.updatedAt = new Date();
        if (entryInfo.textBlock) {
          entryInfo.textBlock.textContent = result.transcript;
        }
        if (entryInfo.timestamp) {
          entryInfo.timestamp.textContent = formatTimestamp(entry.updatedAt);
        }
        retranscribeStatus.textContent = `Re-transcribed with ${getModelName(modelId)} (${result.duration}s)`;
        retranscribeStatus.className = 'transcript-entry__retranscribe-status is-success';

        // Rebuild dropdown to exclude the new model
        rebuildRetranscribeOptions(retranscribeSelect, modelId);
      } else {
        retranscribeStatus.textContent = `Failed: ${result?.error || 'Unknown error'}`;
        retranscribeStatus.classList.add('is-error');
      }
    })
    .catch((error) => {
      retranscribeStatus.textContent = `Failed: ${error?.message || error}`;
      retranscribeStatus.classList.add('is-error');
    })
    .finally(() => {
      retranscribeSelect.disabled = false;
      if (typeof heightAdjustmentCallback === 'function') {
        heightAdjustmentCallback();
      }
    });
}

function rebuildRetranscribeOptions(select, currentModelId) {
  select.innerHTML = '';
  const defaultOpt = document.createElement('option');
  defaultOpt.value = '';
  defaultOpt.textContent = 'Re-transcribe \u25BE';
  defaultOpt.disabled = true;
  defaultOpt.selected = true;
  select.appendChild(defaultOpt);

  ASR_MODELS.forEach((model) => {
    if (model.id === currentModelId) return;
    const opt = document.createElement('option');
    opt.value = model.id;
    opt.textContent = model.name;
    select.appendChild(opt);
  });
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

  if (entry.speaker) {
    const speakerLabel = document.createElement('span');
    speakerLabel.className = 'transcript-entry__speaker';
    speakerLabel.textContent = entry.speaker;
    speakerLabel.dataset.speaker = entry.speaker;
    entryEl.appendChild(speakerLabel);
  }

  const textBlock = document.createElement('div');
  textBlock.className = 'transcript-entry__text';
  textBlock.textContent = entry.text || (entry.status === 'recording' ? 'Capturing audio…' : '');
  entryEl.appendChild(textBlock);

  const { actionBar, retranscribeSelect, retranscribeStatus } = createActionBar(entry);
  entryEl.appendChild(actionBar);

  const metaFooter = document.createElement('div');
  metaFooter.className = 'transcript-entry__footer';
  metaFooter.textContent = entry.status === 'complete'
    ? 'Latest completed dictation.'
    : 'Latest dictation is shown here as it processes.';
  entryEl.appendChild(metaFooter);

  return {
    entryEl,
    textBlock,
    statusBadge,
    timestampEl,
    actionBar,
    retranscribeSelect,
    retranscribeStatus
  };
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
        actionBar,
        retranscribeSelect,
        retranscribeStatus
      } = buildTranscriptEntry(entry);

      container.appendChild(entryEl);

      entryDomMap.set(entry.id, {
        entryEl,
        textBlock,
        statusBadge,
        timestamp: timestampEl,
        actionBar,
        retranscribeSelect,
        retranscribeStatus
      });
    });
  }

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

function findTranscriptByHistoryId(historyId) {
  if (!historyId) {
    return null;
  }
  return transcripts.find((entry) => entry.historyId === historyId) || null;
}

export function setTranscriptHeightCallback(callback) {
  heightAdjustmentCallback = callback;
}

export function initializeTranscriptLog() {
  if (!ensureContainer()) {
    return;
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

export function updateActiveTranscriptText(text, { finalize = false, speaker = null } = {}) {
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
  entry.speaker = speaker || entry.speaker;
  entry.updatedAt = new Date();
  if (finalize) {
    entry.status = 'complete';
    pendingHistoryTranscriptId = entry.id;
    // If this transcript hasn't been linked to a history entry yet,
    // link the most recent unclaimed history entry now.
    if (!entry.historyId && lastHistoryEntryId) {
      entry.historyId = lastHistoryEntryId;
      entry.historyModel = lastHistoryModel;
    }
    if (entry.historyId) {
      pendingHistoryTranscriptId = null;
    }
    activeTranscriptId = null;
  }
  renderTranscripts();
  // After render, ensure the re-transcribe dropdown is enabled if history is linked
  if (finalize && entry.historyId) {
    const domEntry = entryDomMap.get(entry.id);
    if (domEntry && domEntry.retranscribeSelect) {
      domEntry.retranscribeSelect.disabled = false;
      domEntry.retranscribeSelect.title = '';
    }
  }
}

export function finalizeActiveTranscript(text, options = {}) {
  updateActiveTranscriptText(text, { finalize: true, speaker: options.speaker || null });
}

export function resetTranscriptLog() {
  transcripts = [];
  activeTranscriptId = null;
  pendingHistoryTranscriptId = null;
  renderTranscripts();
}

export function setLastHistoryEntry(entryData) {
  if (!entryData || !entryData.id) return;
  lastHistoryEntryId = entryData.id;
  lastHistoryModel = entryData.metadata?.model || null;

  const targetEntry = findTranscriptByHistoryId(entryData.id)
    || (pendingHistoryTranscriptId ? findTranscriptById(pendingHistoryTranscriptId) : null)
    || transcripts.find((t) => t.status === 'complete' && !t.historyId)
    || (activeTranscriptId && findTranscriptById(activeTranscriptId))
    || transcripts.find((t) => t.status === 'complete');

  if (targetEntry) {
    targetEntry.historyId = entryData.id;
    targetEntry.historyModel = lastHistoryModel;
    pendingHistoryTranscriptId = null;

    // Re-render so the action bar state/options are in sync.
    renderTranscripts();

    const domEntry = entryDomMap.get(targetEntry.id);
    if (domEntry?.retranscribeSelect) {
      domEntry.retranscribeSelect.disabled = false;
      domEntry.retranscribeSelect.title = '';
    }
    if (domEntry?.actionBar) {
      domEntry.actionBar.classList.remove('is-hidden');
    }
  }
  logMessage(`[TranscriptLog] History entry linked: ${entryData.id} (model: ${lastHistoryModel})`);
}

export function getLastHistoryId() {
  return lastHistoryEntryId;
}

export function handleQuickRetranscribeResult(resultData) {
  if (!resultData) return;

  const isAutoTriggered = !!resultData.autoTriggered;

  const recentEntry = findTranscriptByHistoryId(resultData.entryId)
    || transcripts.find((t) => t.status === 'complete');
  if (!recentEntry) {
    logMessage('[TranscriptLog] No transcript found to update with quick retranscribe result.');
    return;
  }

  const domEntry = entryDomMap.get(recentEntry.id);
  if (!domEntry) return;

  if (resultData.success) {
    if (isAutoTriggered) {
      // Auto-triggered: show alternative without replacing text
      if (!recentEntry.originalText) {
        recentEntry.originalText = recentEntry.text;
      }
      // Store the alternative but don't swap text yet
      recentEntry.alternativeText = resultData.transcript;
      recentEntry.alternativeModel = resultData.modelId;

      if (domEntry.retranscribeStatus) {
        // Clear any prior content
        domEntry.retranscribeStatus.innerHTML = '';

        const label = document.createElement('span');
        label.textContent = `Alternative ready (${getModelName(resultData.modelId)}, ${resultData.duration}s)`;
        domEntry.retranscribeStatus.appendChild(label);

        const useBtn = document.createElement('button');
        useBtn.type = 'button';
        useBtn.className = 'transcript-entry__use-alt-btn';
        useBtn.textContent = 'Use this';
        useBtn.addEventListener('click', () => {
          // Swap the text
          recentEntry.text = resultData.transcript;
          recentEntry.historyModel = resultData.modelId;
          recentEntry.updatedAt = new Date();
          if (domEntry.textBlock) {
            domEntry.textBlock.textContent = resultData.transcript;
          }
          if (domEntry.timestamp) {
            domEntry.timestamp.textContent = formatTimestamp(recentEntry.updatedAt);
          }
          // Re-paste via clipboard
          if (window.electronAPI && typeof window.electronAPI.repaste === 'function') {
            window.electronAPI.repaste(resultData.transcript);
          }
          // Update status
          domEntry.retranscribeStatus.innerHTML = '';
          domEntry.retranscribeStatus.textContent = `Switched to ${getModelName(resultData.modelId)}`;
          domEntry.retranscribeStatus.className = 'transcript-entry__retranscribe-status is-success';
          if (domEntry.retranscribeSelect) {
            rebuildRetranscribeOptions(domEntry.retranscribeSelect, resultData.modelId);
          }
          if (typeof heightAdjustmentCallback === 'function') {
            heightAdjustmentCallback();
          }
        });
        domEntry.retranscribeStatus.appendChild(useBtn);

        domEntry.retranscribeStatus.className = 'transcript-entry__retranscribe-status is-alt-ready';
      }
    } else {
      // Manual trigger: replace text immediately (existing behavior)
      if (!recentEntry.originalText) {
        recentEntry.originalText = recentEntry.text;
      }
      recentEntry.text = resultData.transcript;
      recentEntry.historyModel = resultData.modelId;
      recentEntry.updatedAt = new Date();

      if (domEntry.textBlock) {
        domEntry.textBlock.textContent = resultData.transcript;
      }
      if (domEntry.timestamp) {
        domEntry.timestamp.textContent = formatTimestamp(recentEntry.updatedAt);
      }
      if (domEntry.retranscribeStatus) {
        domEntry.retranscribeStatus.textContent = `Re-transcribed with ${getModelName(resultData.modelId)} (${resultData.duration}s)`;
        domEntry.retranscribeStatus.className = 'transcript-entry__retranscribe-status is-success';
      }
      if (domEntry.retranscribeSelect) {
        rebuildRetranscribeOptions(domEntry.retranscribeSelect, resultData.modelId);
      }
    }
  } else {
    if (domEntry.retranscribeStatus) {
      const prefix = isAutoTriggered ? 'Background re-transcribe failed' : 'Quick re-transcribe failed';
      domEntry.retranscribeStatus.textContent = `${prefix}: ${resultData.error || 'Unknown error'}`;
      domEntry.retranscribeStatus.className = 'transcript-entry__retranscribe-status is-error';
    }
  }

  if (typeof heightAdjustmentCallback === 'function') {
    heightAdjustmentCallback();
  }
}

/**
 * Toggle visual feedback on the most recent transcript entry during re-transcription.
 * @param {boolean} active  True to show shimmer, false to remove it.
 */
export function setRetranscribingState(active) {
  const recentEntry = transcripts.find((t) => t.status === 'complete');
  if (!recentEntry) return;
  const domEntry = entryDomMap.get(recentEntry.id);
  if (!domEntry || !domEntry.entryEl) return;

  if (active) {
    domEntry.entryEl.classList.add('is-retranscribing');
    if (domEntry.retranscribeStatus) {
      domEntry.retranscribeStatus.textContent = 'Re-transcribing...';
      domEntry.retranscribeStatus.className = 'transcript-entry__retranscribe-status';
    }
  } else {
    domEntry.entryEl.classList.remove('is-retranscribing');
  }
}
