// Modularized renderer.js entry point
// Imports and initializes all renderer logic

import { drawWaveform } from '../shared/renderer_waveform.js';
import { registerIPCHandlers } from '../shared/renderer_ipc.js';
import { logMessage } from '../shared/renderer_utils.js';
import { initializeStatusIndicator } from '../shared/renderer_state.js';
import { initializeControls } from '../shared/renderer_controls.js';
import { initializeTranscriptLog } from '../shared/renderer_transcript_log.js';

// Initialize modules
registerIPCHandlers();

// Initialize status indicator to grey after DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  console.log('[Renderer] DOM loaded, initializing status indicator to grey');
  initializeStatusIndicator();
  initializeControls();
  drawWaveform();
  initializeTranscriptLog();
});

logMessage('Renderer process started.');
