#!/usr/bin/env bash
# Build synthetic footage and a 120 BPM click track, so you can try the whole
# pipeline without touching real wedding footage.
#
#   bash tools/make_sample_footage.sh
#   python -m video_editor select sample/footage
#
set -euo pipefail

OUT="${1:-sample}"
mkdir -p "$OUT/footage"

echo "Building sample footage in $OUT/footage ..."

# A long "full day" recording, with a moving test pattern and a tone.
ffmpeg -hide_banner -v error -y \
  -f lavfi -i "testsrc2=size=1280x720:rate=30:duration=120" \
  -f lavfi -i "sine=frequency=440:duration=120" \
  -c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p -c:a aac -shortest \
  "$OUT/footage/full_day.mp4"

# A few separate clips, as if handed over by a second camera.
ffmpeg -hide_banner -v error -y \
  -f lavfi -i "color=c=orange:size=1280x720:rate=30:duration=10" \
  -f lavfi -i "sine=frequency=300:duration=10" \
  -c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p -c:a aac -shortest \
  "$OUT/footage/haldi.mp4"

ffmpeg -hide_banner -v error -y \
  -f lavfi -i "smptebars=size=1280x720:rate=30:duration=12" \
  -f lavfi -i "sine=frequency=800:duration=12" \
  -c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p -c:a aac -shortest \
  "$OUT/footage/dance.mp4"

# One deliberately silent clip, to prove the silent-track fallback works.
ffmpeg -hide_banner -v error -y \
  -f lavfi -i "color=c=navy:size=1280x720:rate=30:duration=8" \
  -c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p -an \
  "$OUT/footage/vidaai.mp4"

# A 120 BPM click track with a kick on every other beat: something to detect.
ffmpeg -hide_banner -v error -y \
  -f lavfi -i "aevalsrc='0.8*sin(2*PI*440*t)*exp(-24*mod(t,0.5)) + 0.5*sin(2*PI*110*t)*exp(-9*mod(t,1.0))':d=90:s=44100" \
  -c:a aac "$OUT/song.m4a"

echo
echo "Done. Try:"
echo "  python -m video_editor select \"$OUT/footage\""
echo "  python -m video_editor arrange  --mode story"
echo "  python -m video_editor music    --song \"$OUT/song.m4a\" --snap bar"
echo "  python -m video_editor emotions --no-review"
echo "  python -m video_editor render   --audio mix"
