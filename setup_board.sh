#!/usr/bin/env bash
#
# Coralboard one-shot setup - run this ON THE BOARD after copying this folder.
# Installs the Python venv + Gemma runtime (CPU). Vision needs nothing extra:
# it runs on the NPU via the preinstalled SyNAP CLIs.
#
#   ./setup_board.sh
#
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
echo "==> Coralboard demos setup  ($HERE)"

# root on the board has no sudo; on a normal host use sudo.
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="$(command -v sudo || true)"

# /tmp on the board is a small tmpfs (RAM) - too small to unpack big wheels there.
# Point TMPDIR at disk so wheels unpack onto the eMMC.
export TMPDIR="$HERE/.tmp"; mkdir -p "$TMPDIR"

# 0. Swap (best-effort) ----------------------------------------------------
# 2 GB RAM is tight; if pip ever falls back to a source build (e.g. no matching
# Pillow wheel) it can OOM. Add a small swapfile when there's no swap yet. All
# best-effort: a failure here never blocks setup (the prebuilt wheels normally
# need no compile at all).
if [ "$(id -u)" -eq 0 ] && command -v mkswap >/dev/null 2>&1; then
  has_swap="$(awk 'NR>1{n++} END{print n+0}' /proc/swaps 2>/dev/null || echo 0)"
  if [ "$has_swap" -eq 0 ] && [ ! -f "$HERE/.swapfile" ]; then
    echo "==> no swap found; creating a 2 GB swapfile (best-effort)"
    { fallocate -l 2G "$HERE/.swapfile" || dd if=/dev/zero of="$HERE/.swapfile" bs=1M count=2048; } 2>/dev/null \
      && chmod 600 "$HERE/.swapfile" && mkswap "$HERE/.swapfile" >/dev/null 2>&1 \
      && swapon "$HERE/.swapfile" 2>/dev/null \
      && echo "==> swap on ($HERE/.swapfile)" \
      || { echo "!! could not enable swap (continuing without it)"; rm -f "$HERE/.swapfile"; }
  fi
fi

# 1. System packages (best-effort) ----------------------------------------
if command -v apt-get >/dev/null 2>&1; then
  echo "==> apt packages"
  $SUDO apt-get update -y || true
  $SUDO apt-get install -y python3 python3-venv python3-pip python3-gi \
      gstreamer1.0-tools gstreamer1.0-plugins-good libgpiod-tools || \
    echo "!! some apt packages failed; gstreamer/gi/libgpiod may be named differently on this image"
else
  echo "!! apt not found - ensure python3-venv, python3-gi, gstreamer, and gpioset are present"
fi

# 2. Python venv + Gemma (CPU, prebuilt wheel - NO torch) ------------------
# --system-site-packages so the venv can see the system python3-gi (GStreamer
# bindings) the camera uses; llama-cpp-python + Pillow come from pip below.
echo "==> python venv + llama-cpp-python (Gemma on CPU; vision uses the NPU/SyNAP)"
python3 -m venv --system-site-packages .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install --no-cache-dir --prefer-binary -r requirements.txt

# 3. NPU sanity check (uses the preinstalled SyNAP models) -----------------
if command -v synap_cli_ic >/dev/null 2>&1; then
  echo "==> NPU classification (synap_cli_ic) available"
else
  echo "!! synap_cli_ic not found - hello_world vision needs the board's NPU"
fi
command -v synap_cli_od >/dev/null 2>&1 && echo "==> NPU detection (synap_cli_od) available" \
  || echo "!! synap_cli_od not found - hello_world detection step will degrade"

# 4. Gemma weights ---------------------------------------------------------
if [ ! -f models/gemma-3-270m-Q8_0.gguf ]; then
  echo "==> fetching Gemma weights"
  ./models/fetch_models.sh
fi
echo "==> Gemma GGUF present"

# run_board.sh ships with the repo (tracked), so there's nothing to generate here.

echo
echo "==> done"
echo "   Try:  ./run_board.sh hello      (open http://<board-ip>:8090)"
