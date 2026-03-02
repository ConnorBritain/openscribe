// renderer_ui.js
// DOM element references and UI variables

export const statusDot = document.getElementById('status-dot');
export const handyStatusDot = document.getElementById('handy-status-dot');
export const stopButton = document.getElementById('stop-button');
export const cancelButton = document.getElementById('cancel-button');
export const modeIndicator = document.getElementById('mode-indicator');
export const processingIndicator = document.getElementById('processing-indicator');
export const handyModeIndicator = document.getElementById('handy-mode-indicator');
export const handyProcessingIndicator = document.getElementById('handy-processing-indicator');
export const activityPill = document.getElementById('activity-pill');
export const activityLabel = document.getElementById('activity-label');
export const activityIcon = document.getElementById('activity-icon');
export const pillCancelButton = document.getElementById('pill-cancel-button');
export const alwaysOnTopButton = document.getElementById('always-on-top-button');
export const wakeWordToggleButton = document.getElementById('wakeword-toggle');
export const logContent = document.getElementById('log-content');
export const canvas = document.getElementById('waveform-canvas');
export const amplitudes = new Array(100).fill(0);
export const handyLevels = new Array(16).fill(0);
