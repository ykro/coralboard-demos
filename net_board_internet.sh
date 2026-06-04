#!/usr/bin/env bash
#
# Give the Coralboard internet over USB — ONE command (run on the Mac, in a real
# terminal so it can ask for your sudo password).
#
#   ./net_board_internet.sh
#
# It auto-detects everything:
#   · the board's usb0 IP via adb        → derives the gateway (.1) and subnet
#   · the Mac's USB-gadget interface     → the one to give the .1 address
#   · the Mac's upstream interface       → the one with internet (Wi-Fi/Ethernet)
# then configures BOTH sides (Mac NAT + board default route/DNS) and pings out.
#
set -euo pipefail

ADB="$(command -v adb || echo "$HOME/Library/Android/sdk/platform-tools/adb")"
[-x "$ADB" ] || { echo " adb not found (install Android platform-tools)"; exit 1; }
"$ADB" get-state >/dev/null 2>&1 || { echo " board not reachable over adb (plug USB / check 'adb devices')"; exit 1; }

# --- 1. board IP + derived gateway/subnet ----------------------------------
BOARD_IP="$("$ADB" shell "ip -4 -o addr show usb0 2>/dev/null" | awk '{print $4}' | cut -d/ -f1 | tr -d '\r')"
[-n "$BOARD_IP" ] || { echo " couldn't read the board's usb0 IP (is USB networking up?)"; exit 1; }
PREFIX="${BOARD_IP%.*}"          # 192.168.137
GW="${PREFIX}.1"                 # gateway the Mac will own
SUBNET="${PREFIX}.0/24"
echo "• board usb0 = $BOARD_IP  →  gateway $GW  (subnet $SUBNET)"

# --- 2. Mac upstream + Wi-Fi device ----------------------------------------
UPSTREAM="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')"
[-n "$UPSTREAM" ] || { echo " no default route on the Mac (connect to internet first)"; exit 1; }
WIFI="$(networksetup -listallhardwareports 2>/dev/null | awk '/Wi-Fi|AirPort/{getline; print $2}')"
echo "• upstream (internet) = $UPSTREAM"

# --- 3. detect the USB-gadget interface ------------------------------------
# Prefer one already on the board's subnet; else the first ACTIVE ethernet that
# is neither the upstream nor Wi-Fi (skip virtual interfaces).
GADGET=""
for i in $(ifconfig -l); do
  case "$i" in lo*|gif*|stf*|awdl*|llw*|utun*|bridge*|ap*|p2p*|anpi*) continue;; esac
  [ "$i" = "$UPSTREAM" ] && continue
  [ "$i" = "$WIFI" ] && continue
  ifconfig "$i" 2>/dev/null | grep -q "status: active" || continue
  if ifconfig "$i" 2>/dev/null | grep -q "inet ${PREFIX}\."; then GADGET="$i"; break; fi
  [ -z "$GADGET" ] && GADGET="$i"          # fallback: first active candidate
done
[-n "$GADGET" ] || { echo " couldn't find the USB-gadget interface (is the board's USB plugged into the Mac?)"; exit 1; }
echo "• USB-gadget interface = $GADGET  →  assigning $GW"

# --- 4. Mac side: address + forwarding + NAT (needs sudo) -------------------
echo "• configuring the Mac (sudo)…"
sudo ifconfig "$GADGET" "$GW" 255.255.255.0
sudo sysctl -w net.inet.ip.forwarding=1 >/dev/null
echo "nat on $UPSTREAM from $SUBNET to any -> ($UPSTREAM)" | sudo pfctl -ef - 2>/dev/null || true

# --- 5. board side: default route + DNS ------------------------------------
echo "• configuring the board (default route + DNS)…"
"$ADB" shell "ip route replace default via $GW dev usb0; printf 'nameserver 8.8.8.8\nnameserver 1.1.1.1\n' > /etc/resolv.conf" >/dev/null 2>&1 || true

# --- 6. verify -------------------------------------------------------------
echo -n "• testing internet from the board… "
if "$ADB" shell "ping -c1 -W2 8.8.8.8 >/dev/null 2>&1 && echo ok" | grep -q ok; then
  echo " board is online"
else
  echo " no ping yet — re-run, or check the Mac firewall / that '$UPSTREAM' has internet"
fi
