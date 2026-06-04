#!/usr/bin/env bash
# Copy this repo to the board over adb (the board is headless, root, no Wi-Fi).
# Uses `git archive` so only tracked files go over; the GGUF weight is pushed
# separately if present (it is git-ignored).
#
#   ./copy_to_board.sh                 # -> /home/root/coralboard-demos
#   ./copy_to_board.sh /home/root/foo  # custom dest
#
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$HERE"
DEST="${1:-/home/root/coralboard-demos}"
ADB="$(command -v adb || echo "$HOME/Library/Android/sdk/platform-tools/adb")"

echo "==> packing tracked files"
git archive -o /tmp/coralboard.tar HEAD
echo "==> pushing to the board"
"$ADB" shell "mkdir -p $DEST"
"$ADB" push /tmp/coralboard.tar "$DEST/coralboard.tar" >/dev/null
"$ADB" shell "cd $DEST && tar xf coralboard.tar && rm coralboard.tar"

# Push the Gemma weight too if it has been fetched locally (it's git-ignored).
if [ -f models/gemma-3-270m-Q8_0.gguf ]; then
  echo "==> pushing Gemma weight (~291 MB)"
  "$ADB" push models/gemma-3-270m-Q8_0.gguf "$DEST/models/gemma-3-270m-Q8_0.gguf" >/dev/null
fi

echo "==> done. On the board:  cd $DEST && ./setup_board.sh && ./run_board.sh hello"
