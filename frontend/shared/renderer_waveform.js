// renderer_waveform.js
// Orchestrates classic waveform and Handy overlay animation frames.

import { renderClassicWaveformFrame } from './renderer_waveform_classic.js';
import { renderHandyOverlayFrame } from './renderer_handy_overlay.js';

let isAnimationRunning = false;

function renderFrame() {
  renderClassicWaveformFrame();
  renderHandyOverlayFrame();

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
