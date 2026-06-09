#!/usr/bin/env bash
#
# demo.sh - pick and launch a Coralboard demo from a menu.
#
#   ./demo.sh                 # show the menu, pick a demo (runs on the laptop, mocked)
#   ./demo.sh reflex          # launch one directly (skips the menu)
#   ./demo.sh narrator --backend template   # extra flags pass through
#   ./demo.sh --board reflex  # run on the board (real hardware) instead of the laptop
#
# Laptop runs use run_laptop.sh (mocked camera/LED/buzzer, real Gemma); --board
# uses run_board.sh (real NPU + peripherals). Open http://localhost:8090 after
# launch (forward the port first on the board: adb forward tcp:8090 tcp:8090).
#
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$HERE"

# Indexed arrays (no associative arrays - macOS ships bash 3.2, which lacks them).
DEMOS=(reflex tripwire narrator hello)
BLURBS=(
  "reactive smart-camera: classify -> category -> RGB LED color"
  "live counter: detect + track objects crossing a drawn line"
  "hybrid: NPU vision + Gemma narrates the scene every few seconds"
  "bring-up self-test: camera + NPU + LED + buzzer + Gemma greeting"
)

RUNNER=run_laptop.sh
WHERE="laptop (mocked hardware, real Gemma)"
if [ "${1:-}" = "--board" ]; then
  RUNNER=run_board.sh
  WHERE="board (real NPU + peripherals)"
  shift || true
fi

DEMO="${1:-}"
if [ -n "$DEMO" ]; then
  shift || true
else
  echo "Coralboard demos - running on the $WHERE"
  echo
  idx=0
  while [ "$idx" -lt "${#DEMOS[@]}" ]; do
    printf "  %d) %-9s %s\n" "$((idx + 1))" "${DEMOS[$idx]}" "${BLURBS[$idx]}"
    idx=$((idx + 1))
  done
  echo
  read -rp "Pick a demo [1-${#DEMOS[@]}]: " choice
  case "$choice" in
    ''|*[!0-9]*) echo "not a number"; exit 1 ;;
  esac
  if [ "$choice" -lt 1 ] || [ "$choice" -gt "${#DEMOS[@]}" ]; then
    echo "out of range"; exit 1
  fi
  DEMO="${DEMOS[$((choice - 1))]}"
fi

# Validate the demo name.
ok=0
for d in "${DEMOS[@]}"; do [ "$d" = "$DEMO" ] && ok=1; done
if [ "$ok" -ne 1 ]; then
  echo "unknown demo '$DEMO' - choose one of: ${DEMOS[*]}"
  exit 1
fi

echo
echo "==> launching '$DEMO' on the $WHERE"
echo "==> open http://localhost:${CORAL_WEB_PORT:-8090}  (Ctrl-C to stop)"
echo
exec "./$RUNNER" "$DEMO" "$@"
