#!/usr/bin/env bash
#
# run_on_board.sh - from your COMPUTER, run a demo ON THE BOARD in one command.
#
# It does everything the manual two-terminal flow does:
#   1. checks the board is connected over adb
#   2. (optional) deploys the latest committed code with copy_to_board.sh
#   3. forwards the web port so you can open it from your computer
#   4. opens http://localhost:<port> in your browser
#   5. runs the demo on the board in the FOREGROUND, so Ctrl-C here stops it
#      cleanly on the board (LED off, camera released)
#
#   ./run_on_board.sh                  # menu, then run on the board
#   ./run_on_board.sh reflex           # run reflex on the board
#   ./run_on_board.sh --deploy reflex  # copy latest committed code to the board first
#   ./run_on_board.sh narrator 8095    # use a different web port
#   ./run_on_board.sh --no-open hello  # don't auto-open the browser
#   ./run_on_board.sh --dry-run reflex # print what it would do, run nothing
#
# This is the BOARD path (real NPU + camera + LED). For the laptop (mocked)
# path, use ./demo.sh or ./run_laptop.sh instead.
#
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$HERE"
ADB="$(command -v adb || echo "$HOME/Library/Android/sdk/platform-tools/adb")"
DEST="/home/root/coralboard-demos"

DEMOS=(reflex tripwire narrator hello)
BLURBS=(
  "reactive smart-camera: classify -> category -> RGB LED color"
  "live counter: detect + track objects crossing a drawn line"
  "hybrid: NPU vision + Gemma narrates the scene every few seconds"
  "bring-up self-test: camera + NPU + LED + buzzer + Gemma greeting"
)

DEPLOY=0; OPEN=1; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --deploy)  DEPLOY=1; shift ;;
    --no-open) OPEN=0; shift ;;
    --dry-run) DRY=1; shift ;;
    --) shift; break ;;
    -*) echo "unknown flag: $1"; exit 1 ;;
    *) break ;;
  esac
done

DEMO="${1:-}"; PORT="${2:-8090}"

# --- adb reachable + a board attached -------------------------------------
if [ ! -x "$ADB" ] && ! command -v adb >/dev/null 2>&1; then
  echo "adb not found. Install Android platform-tools (see README Prerequisites)."
  exit 1
fi
if [ "$("$ADB" get-state 2>/dev/null)" != "device" ]; then
  echo "No board over adb. Connect it by USB and check 'adb devices' (see HARDWARE.md)."
  exit 1
fi

# --- pick the demo (menu if not given) ------------------------------------
if [ -z "$DEMO" ]; then
  echo "Run a demo ON THE BOARD (real NPU + camera + LED)"
  echo
  idx=0
  while [ "$idx" -lt "${#DEMOS[@]}" ]; do
    printf "  %d) %-9s %s\n" "$((idx + 1))" "${DEMOS[$idx]}" "${BLURBS[$idx]}"
    idx=$((idx + 1))
  done
  echo
  read -rp "Pick a demo [1-${#DEMOS[@]}]: " choice
  case "$choice" in ''|*[!0-9]*) echo "not a number"; exit 1 ;; esac
  if [ "$choice" -lt 1 ] || [ "$choice" -gt "${#DEMOS[@]}" ]; then echo "out of range"; exit 1; fi
  DEMO="${DEMOS[$((choice - 1))]}"
fi
ok=0; for d in "${DEMOS[@]}"; do [ "$d" = "$DEMO" ] && ok=1; done
if [ "$ok" -ne 1 ]; then echo "unknown demo '$DEMO' - choose one of: ${DEMOS[*]}"; exit 1; fi

# --- browser opener (cross-platform) --------------------------------------
open_url() {
  case "$(uname)" in
    Darwin) open "$1" 2>/dev/null || true ;;
    Linux)  xdg-open "$1" 2>/dev/null || true ;;
    *)      command -v start >/dev/null 2>&1 && start "$1" || echo "open $1 in your browser" ;;
  esac
}

RUN_CMD="cd $DEST && CORAL_WEB_PORT=$PORT ./run_board.sh $DEMO"

if [ "$DRY" -eq 1 ]; then
  echo "[dry-run] deploy=$DEPLOY open=$OPEN port=$PORT demo=$DEMO"
  [ "$DEPLOY" -eq 1 ] && echo "[dry-run] ./copy_to_board.sh $DEST"
  echo "[dry-run] $ADB forward tcp:$PORT tcp:$PORT"
  [ "$OPEN" -eq 1 ] && echo "[dry-run] open http://localhost:$PORT"
  echo "[dry-run] $ADB shell -t \"$RUN_CMD\""
  exit 0
fi

# --- deploy (optional) ----------------------------------------------------
if [ "$DEPLOY" -eq 1 ]; then
  echo "==> deploying latest committed code to the board"
  ./copy_to_board.sh "$DEST"
fi

# --- board has a usable venv? ---------------------------------------------
if ! "$ADB" shell "test -x $DEST/.venv/bin/python" 2>/dev/null; then
  echo "The board has no venv at $DEST/.venv."
  echo "Deploy + set it up first:  ./run_on_board.sh --deploy $DEMO   then on the board: ./setup_board.sh"
  exit 1
fi

# --- forward the port, open the browser, run the demo in the foreground ---
"$ADB" forward "tcp:$PORT" "tcp:$PORT" >/dev/null
# Remove the forward when we exit (clean up after Ctrl-C).
trap '"$ADB" forward --remove tcp:'"$PORT"' >/dev/null 2>&1 || true' EXIT

if [ "$OPEN" -eq 1 ]; then
  ( sleep 5; open_url "http://localhost:$PORT" ) &   # the web server binds within a couple seconds
fi

echo "==> running '$DEMO' on the board  ·  web: http://localhost:$PORT  ·  Ctrl-C to stop"
# -t allocates a PTY so Ctrl-C here is delivered as SIGINT to the demo on the
# board -> its clean shutdown runs (LED off, camera released).
"$ADB" shell -t "$RUN_CMD"
