#!/usr/bin/env bash
# Build synthetic footage and a 120 BPM track, so you can try the whole
# pipeline without touching real footage. Nothing here is checked into the
# repo: ffmpeg generates it all from its own test sources.
#
#   bash scripts/make_sample_footage.sh
#   PYTHONPATH=src python -m video_editor select sample/footage
#
set -euo pipefail

OUT="${1:-sample}"
PARTS="$OUT/.parts"
mkdir -p "$OUT/footage" "$PARTS"

echo "Building sample footage in $OUT/footage ..."

# shot <destination> <lavfi pattern> <tone hz> <seconds>
# The pattern is a bare source name; its options are appended with '=' because
# that is what lavfi wants for the first one (smptebars=size=..., not ':').
shot() {
  ffmpeg -hide_banner -v error -y \
    -f lavfi -i "$2=size=1280x720:rate=30:duration=$4" \
    -f lavfi -i "sine=frequency=$3:duration=$4" \
    -c:v libx264 -preset ultrafast -crf 30 -pix_fmt yuv420p \
    -c:a aac -shortest "$1"
}

# Same, for a flat colour, whose own option already carries the '='.
colour_shot() {  # colour_shot <destination> <colour> <tone hz> <seconds>
  ffmpeg -hide_banner -v error -y \
    -f lavfi -i "color=c=$2:size=1280x720:rate=30:duration=$4" \
    -f lavfi -i "sine=frequency=$3:duration=$4" \
    -c:v libx264 -preset ultrafast -crf 30 -pix_fmt yuv420p \
    -c:a aac -shortest "$1"
}

# A long recording made of six distinct shots, so the automatic detector has
# real scene cuts to find - at 10, 20, 30, 40 and 50 seconds.
shot "$PARTS/s1.mp4" "smptebars"   440 10
shot "$PARTS/s2.mp4" "testsrc2"    300 10
shot "$PARTS/s3.mp4" "rgbtestsrc"  700 10
shot "$PARTS/s4.mp4" "smptehdbars" 880 10
shot "$PARTS/s5.mp4" "testsrc"     220 10
shot "$PARTS/s6.mp4" "smptebars"   560 10

# Relative names only. ffmpeg resolves paths in a concat list against the
# directory the list itself lives in, which keeps this working on Windows,
# where an absolute MSYS path like /c/Users/... means nothing to ffmpeg.
: > "$PARTS/list.txt"
for f in "$PARTS"/s*.mp4; do
  printf "file '%s'\n" "$(basename "$f")" >> "$PARTS/list.txt"
done
ffmpeg -hide_banner -v error -y -f concat -safe 0 -i "$PARTS/list.txt" \
  -c copy "$OUT/footage/full_day.mp4"

# A couple of separate clips, as if from a second camera. The names are chosen
# so the preset can file them into segments automatically.
colour_shot "$OUT/footage/haldi_cam2.mp4" "orange" 200 12
shot        "$OUT/footage/dance_cam2.mp4" "testsrc2" 900 12

# One deliberately silent clip, to prove the silent-track fallback works.
ffmpeg -hide_banner -v error -y \
  -f lavfi -i "color=c=navy:size=1280x720:rate=30:duration=8" \
  -c:v libx264 -preset ultrafast -crf 30 -pix_fmt yuv420p -an \
  "$OUT/footage/vidaai_cam2.mp4"

# A 120 BPM track: a click on every beat, a kick on every other one.
ffmpeg -hide_banner -v error -y \
  -f lavfi -i "aevalsrc='0.8*sin(2*PI*440*t)*exp(-24*mod(t,0.5)) + 0.5*sin(2*PI*110*t)*exp(-9*mod(t,1.0))':d=120:s=44100" \
  -c:a aac "$OUT/song.m4a"

rm -rf "$PARTS"

echo
echo "Done. Everything below is generated - delete $OUT/ whenever you like."
echo
echo "  PYTHONPATH=src python -m video_editor run \"$OUT/footage\" \\"
echo "      --name Demo --preset marriage --minutes 1 \\"
echo "      --song \"$OUT/song.m4a\" --json"
