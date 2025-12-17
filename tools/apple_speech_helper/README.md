# Apple Speech Helper (on-device, file-based)

Small macOS helper app used by the Python backend to run Apple’s `Speech` framework **on-device** for WAV files.

## Build

```bash
bash tools/apple_speech_helper/build.sh
```

Produces `tools/apple_speech_helper/dist/AppleSpeechHelper.app`.

## Manual run (example)

```bash
open -n tools/apple_speech_helper/dist/AppleSpeechHelper.app --args \
  --input-file data/history/audio/<id>.wav \
  --output-json /tmp/apple_speech_out.json \
  --done-file /tmp/apple_speech_done.json \
  --locale en-US \
  --chunk-seconds 20 \
  --overlap-seconds 1.0 \
  --timeout-seconds 60
```

