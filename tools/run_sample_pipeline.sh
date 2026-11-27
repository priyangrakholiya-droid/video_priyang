#!/usr/bin/env bash
# End-to-end smoke test: builds sample footage, runs all five steps
# unattended, and checks a real film came out the other end.
#
#   bash tools/run_sample_pipeline.sh
#
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="sample"
PROJECT="sample-run"

bash tools/make_sample_footage.sh "$OUT"

rm -rf "projects/$PROJECT"

# Name, preset and target length come from flags, so only the clip selections
# are piped in. Files are numbered alphabetically:
#   1 dance.mp4   2 full_day.mp4   3 haldi.mp4   4 vidaai.mp4
printf '%s\n' \
  "3 0 6 #haldi" \
  "1 0 5 #dance" \
  "4 #vidaai" \
  "2 10 18 #pheras" \
  "done" \
  | python -m video_editor select "$OUT/footage" \
      --name "$PROJECT" --preset marriage --minutes 1

echo y | python -m video_editor arrange "$PROJECT" --mode story
python -m video_editor music "$PROJECT" --song "$OUT/song.m4a" --snap bar
python -m video_editor emotions "$PROJECT" --no-review
echo y | python -m video_editor render "$PROJECT" --audio mix

FINAL="projects/$PROJECT/06_final/${PROJECT}_final.mp4"
if [ ! -f "$FINAL" ]; then
  echo "FAILED: no final file at $FINAL" >&2
  exit 1
fi
DURATION="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$FINAL")"
echo
echo "PASSED: $FINAL (${DURATION}s)"
python -m video_editor status "$PROJECT"
