# Apple Speech Bench (on-device)

Quick benchmark tool to test Apple’s `Speech` framework on your saved history audio files **forcing on-device recognition**.

## Build

From repo root:

```bash
bash ./tools/apple_speech_bench/build.sh
```

This produces `tools/apple_speech_bench/dist/AppleSpeechBench.app`.

## Run

```bash
bash ./tools/apple_speech_bench/run_sample.sh
```

Or run directly:

```bash
bash ./tools/apple_speech_bench/run_sample.sh "$(pwd)/data/history/audio" "$(pwd)/tools/apple_speech_bench/apple_speech_results.jsonl" 30
```

## Output

Writes JSON Lines to the `--output` path:

- `run_info` header row with locale + config
- `file_result` rows: filename, duration, processing time, RTF, transcript (or error)

## Notes

- First run will prompt for Speech Recognition permission.
- The helper is launched via `open` (LaunchServices). Running the binary directly can crash under TCC with a “missing usage description” error.
- If on-device recognition is not supported for your locale/device, the tool exits with an error.
