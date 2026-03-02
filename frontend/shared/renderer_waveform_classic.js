// renderer_waveform_classic.js
// Handles classic waveform drawing on canvas.

import { amplitudes } from './renderer_ui.js';
import { currentAudioState } from './renderer_state.js';

let loggedReady = false;
let loggedMissing = false;

function normalizeAmplitude(value) {
  const numeric = Number.isFinite(value) ? value : Number(value) || 0;
  return Math.min(Math.max(numeric / 100, 0), 1);
}

function getClassicRenderContext() {
  const canvas = document.getElementById('waveform-canvas');
  if (!canvas) {
    if (!loggedMissing) {
      console.warn('[Waveform] Canvas element not found yet.');
      loggedMissing = true;
    }
    return null;
  }
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    if (!loggedMissing) {
      console.warn('[Waveform] Canvas context unavailable.');
      loggedMissing = true;
    }
    return null;
  }
  if (!loggedReady) {
    console.log('[Waveform] Canvas context ready.');
    loggedReady = true;
    loggedMissing = false;
  }
  return { canvas, ctx };
}

function clearCanvas(ctx, canvas) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function paintClassicBackground(ctx, canvas) {
  const gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
  gradient.addColorStop(0, '#111722');
  gradient.addColorStop(1, '#0b0f16');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
}

function drawClassicWaveformBars(ctx, canvas) {
  const width = canvas.width;
  const height = canvas.height;
  const barWidth = width / amplitudes.length;
  const maxBarHeight = height * 0.95;
  ctx.fillStyle = '#58a6ff';

  for (let i = 0; i < amplitudes.length; i++) {
    const amplitude = amplitudes[i];
    const normalized = normalizeAmplitude(amplitude);
    const eased = Math.pow(normalized, 0.75);
    const barHeight = Math.max(2, eased * maxBarHeight);
    const x = i * barWidth;
    const y = (height - barHeight) / 2;
    ctx.fillRect(x, y, Math.max(barWidth - 1, 1), barHeight);
  }
}

function drawClassicIdleDots(ctx, canvas) {
  const width = canvas.width;
  const height = canvas.height;
  const midY = Math.round(height / 2);
  const dotSpacing = Math.max(Math.floor(width / 40), 8);
  const dotRadius = 2;
  ctx.fillStyle = 'rgba(88, 166, 255, 0.45)';

  for (let x = dotSpacing / 2; x < width; x += dotSpacing) {
    ctx.beginPath();
    ctx.arc(x, midY, dotRadius, 0, Math.PI * 2);
    ctx.fill();
  }
}

function drawClassic(ctx, canvas) {
  paintClassicBackground(ctx, canvas);
  if (currentAudioState === 'dictation') {
    drawClassicWaveformBars(ctx, canvas);
    return;
  }
  const hasLiveAmplitude = amplitudes.some((value) => value > 2);
  if (hasLiveAmplitude) {
    drawClassicWaveformBars(ctx, canvas);
  } else {
    drawClassicIdleDots(ctx, canvas);
  }
}

export function renderClassicWaveformFrame() {
  const classicContext = getClassicRenderContext();
  if (!classicContext) {
    return;
  }

  const { canvas, ctx } = classicContext;
  clearCanvas(ctx, canvas);
  drawClassic(ctx, canvas);
}
