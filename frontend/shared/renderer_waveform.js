// renderer_waveform.js
// Handles waveform drawing and canvas manipulation

import { amplitudes } from './renderer_ui.js';
import { currentAudioState } from './renderer_state.js';

let isAnimationRunning = false;
let loggedReady = false;
let loggedMissing = false;

function getRenderContext() {
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

function paintBackground(ctx, canvas) {
  const gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
  gradient.addColorStop(0, '#111722');
  gradient.addColorStop(1, '#0b0f16');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
}

function drawWaveformBars(ctx, canvas) {
  const width = canvas.width;
  const height = canvas.height;
  const barWidth = width / amplitudes.length;
  const maxBarHeight = height * 0.95;
  ctx.fillStyle = '#58a6ff';

  for (let i = 0; i < amplitudes.length; i++) {
    const amplitude = amplitudes[i];
    const normalized = Math.min(Math.max(amplitude / 100, 0), 1);
    const eased = Math.pow(normalized, 0.75); // brighten low levels
    const barHeight = Math.max(2, eased * maxBarHeight);
    const x = i * barWidth;
    const y = (height - barHeight) / 2;
    ctx.fillRect(x, y, Math.max(barWidth - 1, 1), barHeight);
  }
}

function drawIdleDots(ctx, canvas) {
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

function renderFrame() {
  const context = getRenderContext();
  if (!context) {
    if (isAnimationRunning) {
      requestAnimationFrame(renderFrame);
    }
    return;
  }

  const { canvas, ctx } = context;
  clearCanvas(ctx, canvas);
  paintBackground(ctx, canvas);

  if (currentAudioState === 'dictation') {
    drawWaveformBars(ctx, canvas);
  } else {
    const hasLiveAmplitude = amplitudes.some((value) => value > 2);
    if (hasLiveAmplitude) {
      drawWaveformBars(ctx, canvas);
    } else {
      drawIdleDots(ctx, canvas);
    }
  }

  if (isAnimationRunning) {
    requestAnimationFrame(renderFrame);
  }
}

export function startWaveformAnimation() {
  if (!isAnimationRunning) {
    isAnimationRunning = true;
    requestAnimationFrame(renderFrame);
  }
}

export function stopWaveformAnimation() {
  isAnimationRunning = false;
}

export function drawWaveform() {
  startWaveformAnimation();
}
