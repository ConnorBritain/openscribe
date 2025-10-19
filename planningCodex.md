# ASR–LLM Split Planning (Codex Notes)

These notes capture the current thinking on separating Dictation (ASR) from Proofing (LLM) in the Professional Dictation Transcriber, plus a pragmatic migration path and a draft message schema.

## Context (Today)
- Backend: Python `main.py` orchestrates `AudioHandler` (PyAudio + VAD + Vosk), `TranscriptionHandler` (Whisper/Parakeet), and `LLMHandler` (Qwen/DeepSeek/GPT-OSS via MLX).
- Frontend: Electron window + tray; IPC uses line-prefixed messages (`STATE:`, `STATUS:`, `FINAL_TRANSCRIPT:`, `TRANSCRIPTION:...`).
- Modes: `dictate` (transcribe and paste), `proofread` and `letter` (transcribe, LLM process, then paste). Wake words + hotkeys drive flow.

## Why Split (Benefits)
- Isolation: Keep the real‑time ASR loop stable even if LLM crashes, stalls, or preloads slowly.
- Latency: Dictation remains snappy; defer heavy model load and streaming to proofing-only moments.
- Memory: Only spin up large LLM weights when needed; scale down when idle.
- Tuning: Independently optimize VAD/Vosk thresholds vs. LLM sampler/temp/top‑p.
- Recovery & DX: Restart proofing without tearing down the mic; simpler, more focused tests and mocks.

## Split Options
- Separate processes (recommended long term):
  - One Python process for ASR; one for LLM. Electron orchestrates both lifecycles.
  - Pros: Best isolation; memory control; clear failure boundaries. Cons: More IPC and supervision logic.
- Single process with hardened boundaries (recommended first step):
  - Keep one Python process; enforce strict interfaces between ASR and LLM; namespaced events and request IDs.
  - Pros: Minimal churn; quick wins. Cons: Still shared memory/GC pressure.
- Separate apps (two tray apps):
  - Very clear UX but highest overhead and user friction; not advised initially.

## Protocol and State (Direction)
- Use explicit, namespaced JSON messages for clarity and forward compatibility.
- Add request IDs for correlation: transcript → proof request → streaming → proof complete.
- Define backpressure: queue or reject concurrent proofing; allow cancel/abort.
- Health: simple heartbeats or periodic `*STATE` messages per service; Electron degrades UI gracefully if a service is down.

## UX Considerations
- Triggers: Keep current hotkeys/wake words but validate conflicts (e.g., don’t start new dictation during proofing paste).
- Indicators: Map ASR state to tray color; overlay proofing “processing” state distinctly (or badge in UI).
- Clipboard ownership: Dictation pastes immediately; proofing pastes only on completion; never override active streaming content in UI.

## Operational Notes
- Startup: Launch ASR fast; lazy‑start LLM on first proof request (toggle with `CT_PRELOAD_LLM=1`).
- Recovery: Independent restart logic; if LLM fails, ASR continues; show actionable status.
- Observability: Split logs/labels to distinguish ASR vs. LLM easily (already partially present via labels).

## Risks and Mitigations
- Increased complexity: Keep schema small and versioned; centralize message handling.
- Races: Serialize transitions (e.g., forbid `start_dictate` while proofing is in `pasting`).
- Resource spikes: Limit concurrent proofing; expose cancel; enforce steady-state GC points.

## Migration Path
1) Single‑process hardening (low risk):
- Introduce JSON events alongside current prefixes; include `id`, `ts`, `type`, and `payload`.
- Namespaces: `DICTATION_*`, `PROOFING_*`, `ERROR`, `HEALTH`.
- Make Electron parse JSON first; fallback to legacy prefixes during transition.

2) Proof request queueing:
- Add a minimal queue with “busy” rejection; implement `ABORT_PROOF` if needed.

3) Optional preload policy:
- Toggle LLM preload per model/mode (e.g., proofing only) and record load durations.

4) Dual‑process split (when ready):
- Spawn `backend-asr` and `backend-llm` separately; Electron routes messages; reuse the same JSON schema.

## Draft JSON IPC Schema (Initial Cut)

Message envelope (from Python → Electron):
```
{
  "type": "DICTATION_STATE" | "PROOFING_STATE" | "TRANSCRIPT" | "PROOF_STREAM" | "PROOF_COMPLETE" | "ERROR" | "HEALTH",
  "id": "uuid-or-short-id",        // correlates requests; omit for health/state ticks
  "ts": 1735920034123,              // ms since epoch
  "payload": { ... }                // type-specific
}
```

Events:
- `DICTATION_STATE` payload:
  - `state`: "inactive" | "preparing" | "activation" | "dictation" | "processing"
  - `programActive`: bool
  - `mic`: { `ok`: bool, `message`?: string }
- `TRANSCRIPT` payload:
  - `mode`: "dictate" | "proofread" | "letter"
  - `text`: string  // final ASR output for this session
  - `durationSec`: number
- `PROOF_REQUEST` (Electron → Python; queueable):
  - `sourceId`: transcript id
  - `mode`: "proofread" | "letter"
  - `prompt`: string
  - `text`: string
- `PROOFING_STATE` payload:
  - `state`: "idle" | "loading_model" | "processing" | "streaming" | "pasting"
  - `model`: string
- `PROOF_STREAM` payload:
  - `phase`: "thinking" | "response"
  - `chunk`: string    // may contain newlines; UI should not trim
- `PROOF_COMPLETE` payload:
  - `success`: bool
  - `resultText`?: string
  - `error`?: string
- `ERROR` payload:
  - `scope`: "ASR" | "LLM" | "IPC"
  - `message`: string
  - `detail`?: string
- `HEALTH` payload:
  - `service`: "ASR" | "LLM"
  - `ok`: bool
  - `note`?: string

Notes:
- Keep legacy text-prefix messages during transition; prefer JSON for new UI features.
- When streaming, emit an initial `thinking` message to initialize UI, then periodic `response` chunks.

## State Transitions (Textual Sketch)
- ASR: inactive → preparing (load Vosk) → activation → dictation → processing → activation.
- LLM: idle → loading_model → processing → streaming → pasting → idle.
- Guardrails: ASR `dictation` cannot re-enter `dictation`; LLM `pasting` blocks new proof requests unless canceled.

## Next‑Session Checklist
- Decide where to introduce JSON IPC first (renderer parse path + Python emit path).
- Add request IDs and a simple ID generator in both directions.
- Map existing UI updates to new JSON events; keep legacy path until parity.
- Define cancel/abort semantics (`ABORT_PROOF`) and maximum concurrent proofs (start with 1).
- Choose LLM preload policy defaults (off; allow `CT_PRELOAD_LLM=1`).
- Plan dual‑process scaffolding (naming, launch order, supervised restarts) if needed later.

## Open Questions
- Do we want per‑mode model pools (proof vs letter) loaded concurrently?
- Should proofing ever operate without a fresh ASR transcript (e.g., manual selection clipboard mode)?
- How should tray icon convey dual-state (ASR + LLM) succinctly without confusion?

## Recommendation (Summary)
- Start with single‑process hardening: JSON events + request IDs + small queue.
- Measure memory/latency; if pressure remains, split LLM into its own process using the same schema.
- Preserve UX: immediate dictation responsiveness; reliable, non‑clobbering proofing streams and paste.

