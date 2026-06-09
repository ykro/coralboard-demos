#!/usr/bin/env bash
# Run a demo on the LAPTOP: mocked hardware + REAL Gemma (the same GGUF the board uses).
#   ./run_laptop.sh hello|reflex|tripwire|narrator
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$HERE"
if [ ! -d .venv ]; then
  echo "Setting up .venv (one time)..."
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi
case "${1:-hello}" in
  hello)    MOD=hello_world.main ;;
  reflex)   MOD=reflex.main ;;
  tripwire) MOD=tripwire.main ;;
  narrator) MOD=narrator.main ;;
  *) echo "usage: ./run_laptop.sh [hello|reflex|tripwire|narrator] [args...]"; exit 1 ;;
esac
shift || true
CORAL_MOCK=1 CORAL_BACKEND=gguf ./.venv/bin/python -m "$MOD" --mock "$@"
