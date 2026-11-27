#!/usr/bin/env bash
# End-to-end smoke test. Builds synthetic footage, runs all five steps
# unattended through the JSON interface, and fails loudly if no film comes out
# or if anything was copied that should not have been.
#
#   bash scripts/run_sample_pipeline.sh
#
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-src}"

# Say exactly which command died. Without this, a CI failure is a bare
# non-zero exit and you are left guessing which of the six phases broke.
trap 'status=$?; echo "" >&2; echo "FAILED at line ${LINENO}: ${BASH_COMMAND}" >&2; echo "       exit status ${status}" >&2; echo "       python: $(python -V 2>&1), ffmpeg: $(ffmpeg -version 2>/dev/null | head -1)" >&2' ERR

echo "python: $(python -V 2>&1)"
echo "ffmpeg: $(ffmpeg -version 2>/dev/null | head -1)"

OUT="sample"
PROJECT="sample-run"
VE="python -m video_editor"

echo "=== 0. is this machine ready?"
$VE doctor

echo "=== 1. build the sample footage"
bash scripts/make_sample_footage.sh "$OUT"

rm -rf "projects/$PROJECT"

echo "=== 2. run all five steps, unattended"
$VE run "$OUT/footage" \
  --name "$PROJECT" \
  --preset marriage \
  --minutes 1 \
  --song "$OUT/song.m4a" \
  --snap bar \
  --audio mix \
  --json > "$OUT/result.json"

python - "$OUT/result.json" <<'PY'
import json, sys
raw = open(sys.argv[1], encoding="utf-8").read()
try:
    result = json.loads(raw)
except json.JSONDecodeError as exc:
    # Print what we actually got: this is the only way to diagnose a CI
    # failure from the log alone.
    sys.exit(f"FAILED: stdout was not JSON ({exc})\n--- stdout ---\n{raw[:4000]}")
if "error" in result:
    sys.exit(
        f"FAILED: the pipeline reported {result.get('error_type')}: "
        f"{result['error']}\n--- full document ---\n{raw[:4000]}"
    )
for step in ("select", "arrange", "music", "emotions", "render"):
    if step not in result["steps_done"]:
        sys.exit(f"FAILED: step {step} did not complete")
if not result.get("rendered"):
    sys.exit("FAILED: nothing was rendered")
music = result.get("music")
if not music:
    sys.exit(
        "FAILED: a song was passed, so the music step should have run and "
        f"recorded a tempo\n--- full document ---\n{raw[:4000]}"
    )
print(f"  clips      {result['clips']}")
print(f"  runtime    {result['render_duration']}s (target {result['target_duration']}s)")
print(f"  tempo      {music['bpm']} BPM, snapped to {music['snap']}")
print(f"  emotions   {result['by_emotion']}")
print(f"  rendered   {result['rendered']}")
PY

FINAL="projects/$PROJECT/05_output/${PROJECT}_final.mp4"
if [ ! -f "$FINAL" ]; then
  echo "FAILED: no final file at $FINAL" >&2
  exit 1
fi

echo "=== 3. check the film is real"
DURATION="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$FINAL")"
STREAMS="$(ffprobe -v error -show_entries stream=codec_type -of default=nw=1:nk=1 "$FINAL" | sort | tr '\n' ' ')"
echo "  duration: ${DURATION}s"
echo "  streams:  ${STREAMS}"
case "$STREAMS" in
  *audio*video*) ;;
  *) echo "FAILED: expected both an audio and a video stream" >&2; exit 1 ;;
esac

echo "=== 4. check no footage was copied into the project"
# Exactly one video file may exist in a project: the finished film.
VIDEOS="$(find "projects/$PROJECT" -type f \
  \( -name '*.mp4' -o -name '*.mov' -o -name '*.mkv' -o -name '*.avi' \) | wc -l)"
if [ "$VIDEOS" -ne 1 ]; then
  echo "FAILED: expected 1 video in the project, found $VIDEOS:" >&2
  find "projects/$PROJECT" -type f \
    \( -name '*.mp4' -o -name '*.mov' -o -name '*.mkv' -o -name '*.avi' \) >&2
  exit 1
fi
echo "  1 video in the project, as intended (the film itself)"

echo "=== 5. the definitions that were written instead"
find "projects/$PROJECT" -type f \( -name '*.json' -o -name '*.csv' -o -name '*.txt' \) \
  | sort | sed 's|^|  |'

echo "=== 6. state afterwards"
$VE status "$PROJECT"
# Write first, then trim. Piping straight into `head` closes the pipe early,
# and a Python producer killed by SIGPIPE exits non-zero on Linux, which
# `set -o pipefail` turns into a failed build for no real reason.
$VE plan "$PROJECT" > "$OUT/plan.txt"
sed -n '1,20p' "$OUT/plan.txt"

echo
echo "PASSED: $FINAL (${DURATION}s)"
