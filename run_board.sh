#!/usr/bin/env bash
# Run a demo on the board: REAL peripherals + REAL NPU + REAL Gemma (CPU/GGUF).
#   ./run_board.sh hello
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$HERE"
case "${1:-hello}" in
  hello) MOD=hello_world.main ;;
  *) echo "usage: ./run_board.sh [hello] [args...]"; exit 1 ;;
esac
shift || true
CORAL_MOCK=0 CORAL_BACKEND=gguf ./.venv/bin/python -m "$MOD" "$@"
