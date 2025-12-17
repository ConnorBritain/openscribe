#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$ROOT/dist/AppleSpeechBench.app"
REPO_ROOT="$(cd "$ROOT/../.." && pwd)"

if [[ ! -d "$APP" ]]; then
  echo "Missing app bundle. Run: $ROOT/build.sh" >&2
  exit 1
fi

INPUT_DIR="${1:-$REPO_ROOT/data/history/audio}"
OUT_PATH="${2:-$ROOT/apple_speech_results.jsonl}"
MAX_FILES="${3:-25}"

DONE_PATH="$OUT_PATH.done"
rm -f "$OUT_PATH" "$DONE_PATH"

# NOTE: Running the binary directly (AppleSpeechBench.app/Contents/MacOS/...) can crash under TCC.
# Launch via LaunchServices using `open` so macOS can show the permission prompt + read usage strings.
open -n "$APP" --args \
  --input-dir "$INPUT_DIR" \
  --output "$OUT_PATH" \
  --done-file "$DONE_PATH" \
  --locale en-US \
  --max-files "$MAX_FILES" \
  --timeout-seconds 30 \
  --shuffle >/dev/null 2>&1

for _ in {1..120}; do
  [[ -f "$DONE_PATH" ]] && break
  sleep 0.5
done

if [[ ! -f "$DONE_PATH" ]]; then
  echo "Timed out waiting for completion. Partial output (if any): $OUT_PATH" >&2
  exit 2
fi

echo "Done file: $DONE_PATH"
echo "Results:   $OUT_PATH"
tail -n 3 "$DONE_PATH" 2>/dev/null || true
