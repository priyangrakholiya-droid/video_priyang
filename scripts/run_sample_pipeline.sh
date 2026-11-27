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
result = json.load(open(sys.argv[1]))
if "error" in result:
    sys.exit(f"FAILED: the pipeline reported {result['error']}")
for step in ("select", "arrange", "music", "emotions", "render"):
    if step not in result["steps_done"]:
        sys.exit(f"FAILED: step {step} did not complete")
if not result.get("rendered"):
    sys.exit("FAILED: nothing was rendered")
print(f"  clips      {result['clips']}")
print(f"  runtime    {result['render_duration']}s (target {result['target_duration']}s)")
print(f"  tempo      {result['music']['bpm']} BPM, snapped to {result['music']['snap']}")
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
$VE plan "$PROJECT" | head -20

echo
echo "PASSED: $FINAL (${DURATION}s)"
