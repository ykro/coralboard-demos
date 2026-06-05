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
import threading

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
# VERIFIED on the board: this is an ACTIVE-LOW buzzer and the GPIO latches its last
# written value, so 0 = sound (and STAYS sounding until something writes 1). Every
# beep MUST end by writing the idle value 1, or it tones forever. Panic-silence by
# hand: `gpioset gpiochip0 6=1`.
_BUZZER_ON = os.environ.get("CORAL_BUZZER_ON", "0")    # value that SOUNDS (active-low)
_BUZZER_IDLE = os.environ.get("CORAL_BUZZER_IDLE", "1")  # value that is SILENT at rest
# Safety backstop: even on a deliberate toggle-on, force the buzzer OFF after this
# many seconds so it can never be left sounding (e.g. if the page is closed while on).
_BUZZER_MAX_SEC = float(os.environ.get("CORAL_BUZZER_MAX_SEC", "12"))

# Buzzer toggle state (the web "Buzz" button toggles it on/off, never me).
_buzz_state = {"on": False, "timer": None}
_buzz_lock = threading.Lock()


def set_color(hex_color: str) -> None:
    """Set the RGB status LED to the nearest on/off color for `hex_color`."""
    if config.MOCK:
        print(f"(led) {hex_color}")
        return
    _board_set_color(hex_color)


def buzzing() -> bool:
    """True if the buzzer is currently toggled on."""
    return _buzz_state["on"]


def buzz_toggle() -> bool:
    """Toggle the buzzer on/off and return the new state (True = now sounding).
    Only ever called by the user's deliberate web "Buzz" button - never on its own.
    Turning it on arms a safety timer that forces it back off after _BUZZER_MAX_SEC,
    so the buzzer can never be left sounding."""
    if not _BUZZER_ENABLE:
        print("(buzz disabled via CORAL_BUZZER_ENABLE=0)")
        return False
    with _buzz_lock:
        if _buzz_state["on"]:
            _buzz_off_locked()
        else:
            _buzz_on_locked()
        return _buzz_state["on"]


def buzz_off() -> None:
    """Force the buzzer silent. Safe to call anytime (shutdown, panic)."""
    with _buzz_lock:
        _buzz_off_locked()


def _buzz_on_locked() -> None:
    if config.MOCK:
        print("(buzz) ON")
    else:
        _board_buzz_on()
    _buzz_state["on"] = True
    t = threading.Timer(_BUZZER_MAX_SEC, _buzz_watchdog)
    t.daemon = True
    _buzz_state["timer"] = t
    t.start()


def _buzz_off_locked() -> None:
    if not config.MOCK:
        _board_buzz_off()
    else:
        if _buzz_state["on"]:
            print("(buzz) OFF")
    _buzz_state["on"] = False
    if _buzz_state["timer"] is not None:
        _buzz_state["timer"].cancel()
        _buzz_state["timer"] = None


def _buzz_watchdog() -> None:
    with _buzz_lock:
        if _buzz_state["on"]:
            print("(buzz) safety auto-off")
            _buzz_off_locked()


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


def _board_set_buzz(value: str) -> None:
    """Latch the buzzer line to `value`. This board RETAINS the last written GPIO
    value (writing 0 left it sounding), so a plain one-shot write sticks - no held
    process to orphan and keep sounding if the demo is hard-killed."""
    import shutil

    if not shutil.which("gpioset"):
        print("(buzz: gpioset not found)")
        return
    spec = f"{_BUZZER_LINE}={value}"
    try:
        subprocess.run(["gpioset", _BUZZER_CHIP, spec], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    except (OSError, subprocess.SubprocessError):
        print("(buzz: gpioset failed)")


def _board_buzz_on() -> None:
    _board_set_buzz(_BUZZER_ON)


def _board_buzz_off() -> None:
    _board_set_buzz(_BUZZER_IDLE)
