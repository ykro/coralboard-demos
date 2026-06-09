#!/usr/bin/env bash
# Run a demo on the board: REAL peripherals + REAL NPU + REAL Gemma (CPU/GGUF).
#   ./run_board.sh hello|reflex|tripwire|narrator
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$HERE"
LLM_THREADS=2
case "${1:-hello}" in
  hello)    MOD=hello_world.main ;;
  reflex)   MOD=reflex.main ;;
  tripwire) MOD=tripwire.main ;;
  narrator) MOD=narrator.main; LLM_THREADS=1 ;;  # leave a core free for vision
  *) echo "usage: ./run_board.sh [hello|reflex|tripwire|narrator] [args...]"; exit 1 ;;
esac
shift || true
CORAL_MOCK=0 CORAL_BACKEND=gguf CORAL_LLM_THREADS=$LLM_THREADS \
  ./.venv/bin/python -m "$MOD" "$@"
