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

# Buzzer GPIO line (libgpiod). SAFETY CONTRACT: this buzzer sits at the user's ears.
# It must NEVER sound on its own - there is no auto-beep anywhere, and nothing calls
# buzz() except a deliberate press of the web "Buzz" button. Every beep is a single
# fixed-duration pulse that returns the line to SILENCE; we never hold the line down
# (that earlier left it resting in the sounding state -> continuous tone).
# CORAL_BUZZER_ENABLE=0 hard-disables it (escape hatch); default on so the button works.
_BUZZER_ENABLE = os.environ.get("CORAL_BUZZER_ENABLE", "1") == "1"
_BUZZER_CHIP = os.environ.get("CORAL_BUZZER_CHIP", "gpiochip0")
_BUZZER_LINE = os.environ.get("CORAL_BUZZER_LINE", "6")
_BUZZER_ON = os.environ.get("CORAL_BUZZER_ON", "1")  # value gpioset drives during a pulse
_BUZZER_IDLE = os.environ.get("CORAL_BUZZER_IDLE", "0")  # silent resting value (opposite of ON)


def set_color(hex_color: str) -> None:
    """Set the RGB status LED to the nearest on/off color for `hex_color`."""
    if config.MOCK:
        print(f"(led) {hex_color}")
        return
    _board_set_color(hex_color)


def buzz(ms: int = 120) -> None:
    """Beep the buzzer for `ms` milliseconds, then return the line to SILENCE.
    Only ever called by the user's web "Buzz" button - never on its own. Cap the
    duration so a stray value can't hold a long tone."""
    if not _BUZZER_ENABLE:
        print(f"(buzz disabled via CORAL_BUZZER_ENABLE=0) {ms}ms")
        return
    ms = max(1, min(int(ms), 1000))  # hard cap: no multi-second tones at the ears
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

    if not shutil.which("gpioset"):
        print(f"(buzz: gpioset not found) {ms}ms")
        return
    spec = f"{_BUZZER_LINE}={_BUZZER_ON}"
    usec = str(int(ms) * 1000)
    # ONE fixed-duration pulse, then stop. libgpiod v1 ("--mode=time --usec=") and
    # v2 ("-t <ms>ms") differ, so try both. We deliberately do NOT keep a held
    # background process: that is what could leave the line stuck in the sounding
    # state -> a continuous tone. A bounded pulse always ends. Never raise.
    attempts = [
        ["gpioset", "--mode=time", f"--usec={usec}", _BUZZER_CHIP, spec],
        ["gpioset", "-t", f"{int(ms)}ms", _BUZZER_CHIP, spec],
    ]
    for cmd in attempts:
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=int(ms) / 1000 + 2)
            break
        except (subprocess.SubprocessError, OSError):
            continue
    else:
        print(f"(buzz: gpioset failed) {ms}ms")
        return
    # Belt-and-suspenders: explicitly settle the line to its SILENT idle value so a
    # press can never leave the buzzer humming, whatever the line's default rest is.
    try:
        subprocess.run(["gpioset", _BUZZER_CHIP, f"{_BUZZER_LINE}={_BUZZER_IDLE}"],
                       check=False, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=2)
    except (subprocess.SubprocessError, OSError):
        pass
