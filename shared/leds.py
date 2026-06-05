"""Ambient feedback: the onboard RGB status LED + the Sensor HAT buzzer.

REAL (board): drives the kernel LED class for the RGB LED and `gpioset` for the
buzzer. Both were verified present on the Coralboard:

  RGB LED   /sys/class/leds/red:status/brightness    (gpiochip0 line 10)
            /sys/class/leds/green:status/brightness  (gpiochip0 line 11)
            /sys/class/leds/blue:status/brightness   (gpiochip3 line 1)
            max_brightness = 1  -> each channel is on/off, so 7 colors + off.
            Some channels ship with a trigger (e.g. heartbeat); we set the
            trigger to "none" before writing brightness so our value sticks.

  Buzzer    BUZZERn on gpiochip0 line 6 (active buzzer, no PWM) -> pulse the
            line with `gpioset` for the requested duration.

MOCK (laptop): prints the intended state.

Best-effort contract: the real path NEVER raises. If a sysfs node or `gpioset`
is missing, it prints what it would have done, exactly like the mock path. A
demo must never crash over a status LED or a beep.
"""

import os
import subprocess

from . import config

# Channel -> sysfs LED name. Override via env if your image names them differently.
_LED_CHANNELS = {
    "r": os.environ.get("CORAL_LED_RED", "red:status"),
    "g": os.environ.get("CORAL_LED_GREEN", "green:status"),
    "b": os.environ.get("CORAL_LED_BLUE", "blue:status"),
}
_LED_BASE = os.environ.get("CORAL_LED_BASE", "/sys/class/leds")

# Buzzer GPIO line (libgpiod). The "BUZZERn" line is active-LOW on this board:
# driving the line LOW (value 0) makes it sound; HIGH (1) is silent. Confirmed on
# the board (a high pulse stayed silent, a low pulse sounded). Override via env.
_BUZZER_CHIP = os.environ.get("CORAL_BUZZER_CHIP", "gpiochip0")
_BUZZER_LINE = os.environ.get("CORAL_BUZZER_LINE", "6")
_BUZZER_ON = os.environ.get("CORAL_BUZZER_ON", "0")  # value that makes it sound (active-low)


def set_color(hex_color: str) -> None:
    """Set the RGB status LED to the nearest on/off color for `hex_color`."""
    if config.MOCK:
        print(f"(led) {hex_color}")
        return
    _board_set_color(hex_color)


def buzz(ms: int = 120) -> None:
    """Beep the buzzer for `ms` milliseconds."""
    if config.MOCK:
        print(f"(buzz) {ms}ms")
        return
    _board_buzz(ms)


# --- Real board path (best-effort; prints on any failure) ------------------

def _hex_to_onoff(hex_color: str):
    """Map #rrggbb to a per-channel on/off triple (threshold at mid-scale)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return (1, 1, 1)
    r, g, b = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return (int(r >= 128), int(g >= 128), int(b >= 128))


def _write(path: str, value: str) -> bool:
    try:
        with open(path, "w") as f:
            f.write(value)
        return True
    except OSError:
        return False


def _board_set_color(hex_color: str) -> None:
    on = dict(zip("rgb", _hex_to_onoff(hex_color)))
    wrote_any = False
    for ch, name in _LED_CHANNELS.items():
        d = os.path.join(_LED_BASE, name)
        _write(os.path.join(d, "trigger"), "none")  # release any default trigger
        if _write(os.path.join(d, "brightness"), str(on[ch])):
            wrote_any = True
    if not wrote_any:
        print(f"(led: sysfs not writable) {hex_color}")


def _board_buzz(ms: int) -> None:
    import shutil
    import time

    if not shutil.which("gpioset"):
        print(f"(buzz: gpioset not found) {ms}ms")
        return
    spec = f"{_BUZZER_LINE}={_BUZZER_ON}"
    usec = str(int(ms) * 1000)
    # libgpiod v1 ("--mode=time --usec=") and v2 ("-t <ms>ms") differ; try v1,
    # then v2, then a held background process as a last resort. Never raise.
    attempts = [
        ["gpioset", "--mode=time", f"--usec={usec}", _BUZZER_CHIP, spec],
        ["gpioset", "-t", f"{int(ms)}ms", _BUZZER_CHIP, spec],
    ]
    for cmd in attempts:
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=int(ms) / 1000 + 2)
            return
        except (subprocess.SubprocessError, OSError):
            continue
    # Last resort: hold the line in the background for `ms`, then release.
    try:
        p = subprocess.Popen(["gpioset", "--mode=signal", _BUZZER_CHIP, spec],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(int(ms) / 1000)
        p.terminate()
    except (OSError, subprocess.SubprocessError):
        print(f"(buzz: gpioset failed) {ms}ms")
