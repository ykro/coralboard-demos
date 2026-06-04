#!/usr/bin/env bash
#
# Download the Gemma 3 270M weights the hello_world demo needs. Weights are NOT
# in git (too large) - run this once after cloning.
#
#   ./models/fetch_models.sh
#
# Vision needs NO download: it runs on the NPU via the preinstalled SyNAP models.
# npu_live needs no weights at all.
#
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
RUNTIME="gemma-3-270m-Q8_0.gguf"

if [ -f "$RUNTIME" ]; then
  echo "==> $RUNTIME present"
else
  echo "==> downloading $RUNTIME (~291 MB)"
  curl -L -o "$RUNTIME" \
    "https://huggingface.co/unsloth/gemma-3-270m-it-GGUF/resolve/main/gemma-3-270m-it-Q8_0.gguf"
fi

echo "==> done. Runtime model: $HERE/$RUNTIME"
