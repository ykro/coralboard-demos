#!/usr/bin/env bash
#
# Download the Gemma 3 270M weights the hello_world demo needs. Weights are NOT
# in git (too large) - run this once after cloning.
#
#   ./models/fetch_models.sh
#
# Vision needs NO download: it runs on the NPU via the preinstalled SyNAP models.
#
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
RUNTIME="gemma-3-270m-Q8_0.gguf"

URL="https://huggingface.co/unsloth/gemma-3-270m-it-GGUF/resolve/main/gemma-3-270m-it-Q8_0.gguf"
MIN_BYTES=200000000   # the real file is ~291 MB; anything much smaller is an error page, not the model

# File size in bytes, portable across macOS (stat -f%z) and Linux (stat -c%s).
filesize() { stat -f%z "$1" 2>/dev/null || stat -c%s "$1" 2>/dev/null || echo 0; }

if [ -f "$RUNTIME" ] && [ "$(filesize "$RUNTIME")" -ge "$MIN_BYTES" ]; then
  echo "==> $RUNTIME present"
else
  [ -f "$RUNTIME" ] && echo "==> $RUNTIME looks truncated ($(filesize "$RUNTIME") bytes) - re-downloading"
  echo "==> downloading $RUNTIME (~291 MB)"
  # --fail: a 404 / redirect-to-HTML returns non-zero instead of silently writing
  # an error page that only blows up later as a cryptic llama.cpp load failure.
  curl -fL -o "$RUNTIME" "$URL"
  got="$(filesize "$RUNTIME")"
  if [ "$got" -lt "$MIN_BYTES" ]; then
    rm -f "$RUNTIME"
    echo "!! download failed or truncated ($got bytes). Check your connection and the URL:"
    echo "   $URL"
    exit 1
  fi
fi

echo "==> done. Runtime model: $HERE/$RUNTIME ($(filesize "$RUNTIME") bytes)"
