# MLX 0.29.2 Upgrade & MXFP4 GPT-OSS Model Notes

## Upgrade Impact
- `requirements.txt` already lists `mlx_lm`, `mlx-whisper`, and `parakeet-mlx` with minimum versions. Raising `mlx` to `0.29.2` mainly requires upgrading these companion wheels together (e.g. `pip install --upgrade mlx==0.29.2 mlx-lm>=0.28.3 mlx-whisper>=0.4.1 parakeet-mlx>=0.1.1` when released).
- MLX 0.29.x keeps the public Python API stable. `src/llm/llm_handler.py` relies on `mlx_lm.load`, `stream_generate`, and `make_sampler`; their signatures are unchanged. `stream_generate` now yields `GenerationChunk` objects whose `.text` may be empty; existing guards already handle this.
- Speech code in `src/transcription_handler.py` depends on `mlx_whisper` and `parakeet_mlx`. Both bundle MLX-specific kernels, so expect to reinstall matching wheels. If releases lag, the app falls back to mock implementations, temporarily reducing ASR quality without crashing.
- Native dependencies (`openwakeword`, `vosk`, PyAudio, Electron frontend) are unaffected by the MLX bump.

## MXFP4 GPT-OSS Model Integration
- Add `mlx-community/gpt-oss-20b-MXFP4-Q4` to `config.AVAILABLE_LLMS` and corresponding UI copy; ensure weights live under `models/mlx-community/gpt-oss-20b-MXFP4-Q4`.
- MXFP4 is an MLX-native 4-bit float quantization introduced in MLX 0.29. Requires `mlx_lm` ≥ 0.28.3 so `load()` can read `.mlx` shards.
- Expect ~14–15 GB RAM usage and ~14 GB download size—slightly higher than the existing HI Q4 variant. Existing loop mitigation in `src/llm/llm_handler.py` remains applicable because the tokenizer uses the same `analysis/final` channels.
- Check Hugging Face card for tokenizer metadata; if a specific chat template name is required, adjust `create_gpt_oss_chat_prompt` to pass it explicitly.

## Risks & Mitigations
- **Lagging wheels:** Medium risk that `mlx-whisper`/`parakeet-mlx` releases trail MLX 0.29.2. Test installs in a fresh virtualenv; keep current mock fallbacks active.
- **Sampler API shifts:** `mlx_lm.sample_utils.make_sampler` may change required kwargs. Monitor release notes and pin a known-good version if needed.
- **Runtime regressions:** Run `pytest -k gpt_oss`, manual proof/letter flows, and ASR smoke tests after upgrading. Validate MXFP4 load with a minimal `load(..., lazy=True)` + short `stream_generate` call to confirm channel parsing and measure memory usage.

## Validation Findings (Current Environment)
- `mlx==0.29.2`, `mlx-metal==0.29.2`, and `mlx-whisper==0.4.3` install cleanly on Python 3.11 (also worked on 3.9.6 for mlx core).
- `mlx-lm==0.28.3` is the latest published wheel and already includes MXFP4 support; runtime gating now requires ≥0.28.3 before exposing the model.
- `parakeet-mlx` ≥0.1.1 requires Python ≥3.10, so interpreter upgrade remains a prerequisite for full MLX 0.29 adoption.
- CI/electron sandbox lacks Apple Metal access; `import mlx_lm` aborts there, so MXFP4 verification and `pytest -k gpt_oss` must run on real Apple hardware after upgrading.

## Suggested Next Steps
1. Move the project to Python 3.10+, recreate the virtualenv, and install the MLX 0.29.2 wheel stack (including `parakeet-mlx` once compatible).
2. Ensure `mlx-lm` ≥0.28.3 is installed, rerun `pytest -k gpt_oss`, and sanity check MXFP4 streaming with the debug utilities on Apple hardware.
3. Download MXFP4 weights locally, confirm memory footprint (~15 GB), then update `requirements.txt` minimums and finalize UI copy once tests pass.
