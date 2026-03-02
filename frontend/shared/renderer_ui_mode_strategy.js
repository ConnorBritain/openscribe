// renderer_ui_mode_strategy.js
// Centralizes mode-specific UI behavior for classic vs handy layouts.

const UI_MODE_CLASSIC = 'classic';
const UI_MODE_HANDY = 'handy';

const STRATEGIES = {
  [UI_MODE_CLASSIC]: {
    id: UI_MODE_CLASSIC,
    transcriptCollapsedByDefault: false,
    allowWindowResize: true
  },
  [UI_MODE_HANDY]: {
    id: UI_MODE_HANDY,
    transcriptCollapsedByDefault: true,
    allowWindowResize: false
  }
};

let activeUiMode = UI_MODE_CLASSIC;

export function normalizeUiMode(mode) {
  return mode === UI_MODE_HANDY ? UI_MODE_HANDY : UI_MODE_CLASSIC;
}

export function getUiModeStrategy(mode = activeUiMode) {
  const normalized = normalizeUiMode(mode);
  return STRATEGIES[normalized];
}

export function getActiveUiMode() {
  return activeUiMode;
}

export function isHandyModeActive() {
  return activeUiMode === UI_MODE_HANDY;
}

export function activateUiMode(mode) {
  const normalizedMode = normalizeUiMode(mode);
  activeUiMode = normalizedMode;

  document.documentElement.classList.toggle('ui-mode-handy', normalizedMode === UI_MODE_HANDY);
  document.documentElement.classList.toggle('ui-mode-classic', normalizedMode === UI_MODE_CLASSIC);
  document.body.classList.toggle('ui-mode-handy', normalizedMode === UI_MODE_HANDY);
  document.body.classList.toggle('ui-mode-classic', normalizedMode === UI_MODE_CLASSIC);
  document.body.dataset.uiMode = normalizedMode;

  return normalizedMode;
}

export function shouldResizeWindowForActiveMode() {
  return getUiModeStrategy().allowWindowResize;
}

export function applyTranscriptVisibility(collapsed) {
  const responseArea = document.getElementById('response-area');
  const appContainer = document.getElementById('app-container');
  if (!responseArea) {
    return;
  }

  responseArea.dataset.collapsed = collapsed ? 'true' : 'false';
  responseArea.style.display = collapsed ? 'none' : 'flex';

  if (appContainer) {
    appContainer.classList.toggle('is-transcript-collapsed', collapsed);
  }
}

export function applyModeLayoutDefaults() {
  const strategy = getUiModeStrategy();
  applyTranscriptVisibility(strategy.transcriptCollapsedByDefault);
}

export function resolveTranscriptCollapseState({ forceState = null, hasEntries = false, currentCollapsed = false } = {}) {
  const strategy = getUiModeStrategy();
  if (!strategy.allowWindowResize) {
    return true;
  }
  if (forceState === 'collapsed') {
    return true;
  }
  if (forceState === 'expanded') {
    return false;
  }
  if (hasEntries) {
    return false;
  }
  return currentCollapsed;
}

