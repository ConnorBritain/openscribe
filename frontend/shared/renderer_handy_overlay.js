// renderer_handy_overlay.js
// Handles Handy overlay bar animation.

import { handyLevels } from './renderer_ui.js';
import { currentAudioState } from './renderer_state.js';

let cachedHandyBars = null;

function getHandyBars() {
  if (
    Array.isArray(cachedHandyBars) &&
    cachedHandyBars.length > 0 &&
    cachedHandyBars.every((bar) => bar && bar.isConnected)
  ) {
    return cachedHandyBars;
  }

  const container = document.getElementById('handy-bars');
  if (!container) {
    cachedHandyBars = null;
    return [];
  }

  const bars = Array.from(container.querySelectorAll('.handy-bar'));
  cachedHandyBars = bars;
  return bars;
}

function readBarMetrics() {
  const rootStyle = getComputedStyle(document.documentElement);
  const minHeight = Number.parseFloat(rootStyle.getPropertyValue('--handy-bar-min-height'));
  const maxHeight = Number.parseFloat(rootStyle.getPropertyValue('--handy-bar-max-height'));
  return {
    minHeight: Number.isFinite(minHeight) ? minHeight : 4,
    maxHeight: Number.isFinite(maxHeight) ? maxHeight : 20
  };
}

export function renderHandyOverlayFrame() {
  const bars = getHandyBars();
  if (bars.length === 0) {
    return;
  }

  // Match Handy overlay behavior: bars animate during active recording.
  const showBars = currentAudioState === 'dictation';
  const { minHeight, maxHeight } = readBarMetrics();

  for (let i = 0; i < bars.length; i++) {
    const bar = bars[i];
    let level = Number(handyLevels[i]);
    if (!Number.isFinite(level)) {
      level = 0;
    }

    level = Math.min(Math.max(level, 0), 1);
    if (!showBars) {
      level = 0;
    }

    const dynamicRange = Math.max(0, maxHeight - minHeight);
    const height = Math.min(maxHeight, minHeight + (Math.pow(level, 0.7) * dynamicRange));
    const opacity = Math.max(0.2, level * 1.7);
    bar.style.height = `${height.toFixed(2)}px`;
    bar.style.opacity = opacity.toFixed(3);
  }
}
