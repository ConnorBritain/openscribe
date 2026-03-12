// Modularized renderer.js entry point
// Imports and initializes all renderer logic

import { drawWaveform } from '../shared/renderer_waveform.js';
import { registerIPCHandlers } from '../shared/renderer_ipc.js';
import { logMessage } from '../shared/renderer_utils.js';
import { initializeStatusIndicator } from '../shared/renderer_state.js';
import { initializeControls } from '../shared/renderer_controls.js';
import { initializeTranscriptLog } from '../shared/renderer_transcript_log.js';
import { configureIpcContract } from '../shared/ipc_contract.js';
import { activateUiMode, applyModeLayoutDefaults } from '../shared/renderer_ui_mode_strategy.js';

const DEFAULT_HANDY_UI_CONSTANTS = {
  width: 172,
  height: 36,
  cornerRadius: 18,
  bars: {
    count: 9,
    width: 6,
    gap: 3,
    minHeight: 4,
    maxHeight: 20
  }
};

function normalizeHandyUiConstants(raw) {
  const width = Number(raw?.width);
  const height = Number(raw?.height);
  const cornerRadius = Number(raw?.cornerRadius);
  const bars = raw?.bars || {};
  const barCount = Number(bars.count);
  const barWidth = Number(bars.width);
  const barGap = Number(bars.gap);
  const barMinHeight = Number(bars.minHeight);
  const barMaxHeight = Number(bars.maxHeight);

  return {
    width: Number.isFinite(width) && width > 0 ? width : DEFAULT_HANDY_UI_CONSTANTS.width,
    height: Number.isFinite(height) && height > 0 ? height : DEFAULT_HANDY_UI_CONSTANTS.height,
    cornerRadius: Number.isFinite(cornerRadius) && cornerRadius > 0 ? cornerRadius : DEFAULT_HANDY_UI_CONSTANTS.cornerRadius,
    bars: {
      count: Number.isFinite(barCount) && barCount > 0 ? Math.round(barCount) : DEFAULT_HANDY_UI_CONSTANTS.bars.count,
      width: Number.isFinite(barWidth) && barWidth > 0 ? barWidth : DEFAULT_HANDY_UI_CONSTANTS.bars.width,
      gap: Number.isFinite(barGap) && barGap >= 0 ? barGap : DEFAULT_HANDY_UI_CONSTANTS.bars.gap,
      minHeight: Number.isFinite(barMinHeight) && barMinHeight >= 0 ? barMinHeight : DEFAULT_HANDY_UI_CONSTANTS.bars.minHeight,
      maxHeight: Number.isFinite(barMaxHeight) && barMaxHeight > 0 ? barMaxHeight : DEFAULT_HANDY_UI_CONSTANTS.bars.maxHeight
    }
  };
}

function applyHandyUiCssVariables(constants) {
  const root = document.documentElement;
  root.style.setProperty('--handy-width', `${constants.width}px`);
  root.style.setProperty('--handy-height', `${constants.height}px`);
  root.style.setProperty('--handy-radius', `${constants.cornerRadius}px`);
  root.style.setProperty('--handy-bar-count', `${constants.bars.count}`);
  root.style.setProperty('--handy-bar-width', `${constants.bars.width}px`);
  root.style.setProperty('--handy-bar-gap', `${constants.bars.gap}px`);
  root.style.setProperty('--handy-bar-min-height', `${constants.bars.minHeight}px`);
  root.style.setProperty('--handy-bar-max-height', `${constants.bars.maxHeight}px`);
}

function synchronizeHandyBars(constants) {
  const barsContainer = document.getElementById('handy-bars');
  if (!barsContainer) {
    return;
  }

  const desiredCount = Math.max(1, Math.round(constants?.bars?.count || DEFAULT_HANDY_UI_CONSTANTS.bars.count));
  const existingBars = barsContainer.querySelectorAll('.handy-bar');
  if (existingBars.length === desiredCount) {
    return;
  }

  barsContainer.innerHTML = '';
  for (let index = 0; index < desiredCount; index++) {
    const bar = document.createElement('span');
    bar.className = 'handy-bar';
    barsContainer.appendChild(bar);
  }
}

async function initializeHandyUiConstants() {
  try {
    const payload = (
      window.electronAPI &&
      typeof window.electronAPI.loadHandyUiConstants === 'function'
    )
      ? await window.electronAPI.loadHandyUiConstants()
      : DEFAULT_HANDY_UI_CONSTANTS;
    const constants = normalizeHandyUiConstants(payload);
    applyHandyUiCssVariables(constants);
    synchronizeHandyBars(constants);
  } catch (error) {
    console.warn('[Renderer] Falling back to default Handy UI constants.', error);
    applyHandyUiCssVariables(DEFAULT_HANDY_UI_CONSTANTS);
    synchronizeHandyBars(DEFAULT_HANDY_UI_CONSTANTS);
  }
}

async function initializeIpcContract() {
  if (window.electronAPI && typeof window.electronAPI.loadIpcContract === 'function') {
    try {
      const contract = await window.electronAPI.loadIpcContract();
      configureIpcContract(contract);
      return;
    } catch (error) {
      console.warn('[Renderer] Failed to load IPC contract; falling back to defaults.', error);
    }
  }
  configureIpcContract(null);
}

async function initializeUiMode() {
  let mode = 'classic';
  if (window.electronAPI && typeof window.electronAPI.loadUiMode === 'function') {
    try {
      mode = await window.electronAPI.loadUiMode();
    } catch (error) {
      console.warn('[Renderer] Failed to load UI mode; defaulting to classic.', error);
    }
  }

  activateUiMode(mode);
  applyModeLayoutDefaults();

  if (window.electronAPI && typeof window.electronAPI.on === 'function') {
    window.electronAPI.on('ui-mode-updated', (payload) => {
      if (!payload || typeof payload.uiMode !== 'string') {
        return;
      }
      activateUiMode(payload.uiMode);
      applyModeLayoutDefaults();
    });
  }
}

// Initialize status indicator to grey after DOM is ready
document.addEventListener('DOMContentLoaded', async () => {
  await initializeIpcContract();
  registerIPCHandlers();
  await initializeHandyUiConstants();
  await initializeUiMode();
  console.log('[Renderer] DOM loaded, initializing status indicator to grey');
  initializeStatusIndicator();
  initializeControls();
  drawWaveform();
  initializeTranscriptLog();

  // View navigation
  const navHomeBtn = document.getElementById('nav-home-btn');
  const navFtBtn = document.getElementById('nav-ft-btn');
  if (navHomeBtn && window.navAPI) {
    navHomeBtn.addEventListener('click', () => window.navAPI.goHome());
  }
  if (navFtBtn && window.navAPI) {
    navFtBtn.addEventListener('click', () => window.navAPI.goFileTranscribe());
  }
});

logMessage('Renderer process started.');
