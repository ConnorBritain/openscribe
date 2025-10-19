// renderer_paste_proof.js
// Handles the Paste → Proof workflow in the main window UI.

import { logMessage } from './renderer_utils.js';
import { recomputeWindowHeight } from './renderer_expansion_ui.js';

export function initializePasteProofUi() {
  const toggleButton = document.getElementById('paste-proof-button');
  const panel = document.getElementById('paste-proof-area');
  const input = document.getElementById('paste-proof-input');
  const submit = document.getElementById('paste-proof-submit');
  const cancel = document.getElementById('paste-proof-cancel');
  const feedback = document.getElementById('paste-proof-feedback');

  if (!toggleButton || !panel || !input || !submit || !cancel || !feedback) {
    logMessage('Paste proof UI elements missing; skipping initialization.', 'warn');
    return;
  }

  let panelVisible = false;
  let inFlight = false;
  const defaultSubmitLabel = submit.textContent;

  function setFeedback(message, type) {
    feedback.textContent = message || '';
    feedback.classList.remove('show', 'error', 'success');
    if (message) {
      feedback.classList.add('show');
      if (type === 'error') {
        feedback.classList.add('error');
      } else {
        feedback.classList.add('success');
      }
    }
    recomputeWindowHeight();
  }

  function setPanelVisibility(visible) {
    panelVisible = visible;
    panel.style.display = visible ? 'block' : 'none';
    toggleButton.classList.toggle('active', visible);
    if (visible) {
      setFeedback('', null);
      requestAnimationFrame(() => input.focus());
    }
    recomputeWindowHeight();
  }

  async function handleSubmit() {
    if (inFlight) return;

    const text = input.value.trim();
    if (!text) {
      setFeedback('Paste text before starting proof.', 'error');
      return;
    }
    if (!window.electronAPI || typeof window.electronAPI.proofPaste !== 'function') {
      setFeedback('Proofing is unavailable. Restart the app and try again.', 'error');
      return;
    }

    inFlight = true;
    submit.disabled = true;
    cancel.disabled = true;
    toggleButton.disabled = true;
    input.setAttribute('readonly', 'readonly');
    const originalToggleTitle = toggleButton.title;
    toggleButton.title = 'Proof in progress…';
    submit.textContent = 'Proofing…';
    setFeedback('Sending text for proofing. Watch the Proof panel for results.', 'success');

    try {
      const result = await window.electronAPI.proofPaste({ text });
      if (!result || result.ok !== true) {
        const errorMessage = result && result.error ? result.error : 'Unknown error';
        throw new Error(errorMessage);
      }
      setFeedback('Proofing started. Output will appear in the Proof section shortly.', 'success');
      logMessage('Paste → Proof request sent successfully.', 'controls');
    } catch (error) {
      console.error('[PasteProof] Failed to start proofing:', error);
      setFeedback(`Unable to start proofing: ${error.message}`, 'error');
    } finally {
      inFlight = false;
      submit.disabled = false;
      cancel.disabled = false;
      toggleButton.disabled = false;
      input.removeAttribute('readonly');
      toggleButton.title = originalToggleTitle;
      submit.textContent = defaultSubmitLabel;
      recomputeWindowHeight();
    }
  }

  toggleButton.addEventListener('click', () => {
    if (inFlight) return;
    setPanelVisibility(!panelVisible);
  });

  cancel.addEventListener('click', () => {
    if (inFlight) return;
    setPanelVisibility(false);
    input.value = '';
    setFeedback('', null);
  });

  submit.addEventListener('click', () => {
    handleSubmit();
  });

  input.addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault();
      handleSubmit();
    } else if (event.key === 'Escape' && panelVisible && !inFlight) {
      event.preventDefault();
      setPanelVisibility(false);
    }
  });

  logMessage('Paste proof UI initialized.', 'controls');
}
