# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Professional Dictation Transcriber - a real-time speech-to-text application with AI proofreading, built with Python backend, Electron frontend, and local MLX models for privacy-focused dictation.

## Build & Run Commands

```bash
# Development
npm start                  # Start app (Electron + Python backend)
npm run lint               # ESLint check
npm run lint:fix           # Auto-fix linting issues

# Testing
pytest                     # All tests
pytest tests/unit/         # Unit tests only
pytest tests/integration/  # Integration tests
pytest -m "not slow"       # Skip slow tests

# Building
npm run build:python       # Build Python backend (PyInstaller)
npm run build:electron     # Build Electron app
npm run dist               # Full distribution build
bash scripts/build.sh      # Complete macOS build
```

## Architecture

### Process Communication

The app uses a dual-process architecture:
1. **Electron main process** spawns Python as a subprocess
2. **Python backend** communicates via stdout using structured messages
3. **Renderer processes** receive updates via Electron IPC

**IPC Message Flow:**
```
Python stdout → electron_python.js → electron_ipc.js → renderer_ipc.js → UI
```

**Message Format:** `TYPE:JSON_PAYLOAD`

Key message types:
- `STATUS:{"color":"blue","message":"..."}` - Status updates
- `STATE:{"programActive":true,"isDictating":false,...}` - State sync
- `TRANSCRIPT:{"type":"final","text":"..."}` - Transcription results
- `PYTHON_BACKEND_READY` - Startup signal

All Python output must use defined message types. Use `log_text(label, message)` for debugging (suppressed from stdout by default, enable with `CT_VERBOSE=1`).

### Key Modules

**Python Backend (`src/`):**
- `transcription_handler.py` - ASR coordination (Whisper MLX, Parakeet, Voxtral, MedASR, Apple Speech)
- `audio/audio_handler.py` - Microphone input, VAD, ring buffer
- `config/config.py` - Constants, paths, audio parameters
- `config/settings_manager.py` - User settings persistence
- `vocabulary/vocabulary_manager.py` - Custom term learning
- `hotkey_manager.py` - Global keyboard shortcuts (pynput)

**Electron (`electron/`):**
- `electron_python.js` - Python subprocess management
- `electron_ipc.js` - IPC message routing
- `electron_windows.js` - Window creation/management
- `electron_tray.js` - System tray integration

**Frontend (`frontend/`):**
- `shared/renderer_ipc.js` - IPC message handling
- `shared/renderer_state.js` - UI state management
- `main/`, `settings/`, `history/` - Window-specific code

### Data Storage

- `user_settings.json` - User preferences (root directory)
- `data/user_vocabulary.json` - Learned vocabulary
- `models/` - Cached ML models (Whisper, Parakeet, Qwen)
- `vosk/` - Wake word detection models
- `logs/` - Application logs

## Testing

**Pytest markers** (from pytest.ini):
- `@pytest.mark.unit` - Unit tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.performance` - Benchmarks
- `@pytest.mark.slow` - Long-running tests (excluded by default)
- `@pytest.mark.audio` - Audio pipeline tests
- `@pytest.mark.communication` - IPC tests

Tests must handle missing audio/ML libraries gracefully for CI environments.

## Environment Variables

- `CT_VERBOSE=1` - Enable verbose logging to stdout
- `CT_LOG_WHITELIST="LABEL1,LABEL2"` - Whitelist specific log labels

## Hotkeys (macOS)

- `Cmd+Shift+A` - Toggle application active
- `Cmd+Shift+D` - Start dictation
- `Cmd+Shift+S` - Stop dictation
- `Cmd+Shift+R` - Restart application
