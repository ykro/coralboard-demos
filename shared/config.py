"""Shared runtime configuration for the Coralboard demos.

Two independent axes:

1. HARDWARE (MOCK): camera / LEDs / buzzer.
   - MOCK=True  -> fake on a laptop.
   - MOCK=False -> real Coralboard peripherals + the NPU.

2. LANGUAGE MODEL (BACKEND): Gemma 3 270M (used by hello_world only).
   - "gguf"     -> Gemma 3 270M GGUF via llama.cpp (light, fast; laptop + board CPU). Default.
   - "template" -> tiny rule-based stand-in (no model needed).

Key point: `--mock` mocks the HARDWARE but keeps Gemma REAL (gguf), so the
laptop demo uses the exact same model that runs on the board.
"""

import os

# Default to laptop-friendly hardware mock; the board run wrapper sets CORAL_MOCK=0.
MOCK = os.environ.get("CORAL_MOCK", "1") == "1"

# Real Gemma by default (the same GGUF on laptop and board CPU).
BACKEND = os.environ.get("CORAL_BACKEND", "gguf")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Runtime GGUF (Google's gemma-3-270m, Q8_0). fetch_models.sh downloads this name.
MODEL_PATH = os.environ.get(
    "CORAL_MODEL_PATH", os.path.join(_REPO, "models", "gemma-3-270m-Q8_0.gguf")
)

# Generated text: English.
LANG = os.environ.get("CORAL_LANG", "en")

# Local web server. Port 8090 because the board's swupdate service owns 8080.
WEB_HOST = os.environ.get("CORAL_WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("CORAL_WEB_PORT", "8090"))


def set_mock(value: bool) -> None:
    global MOCK
    MOCK = value


def set_backend(value: str) -> None:
    global BACKEND
    BACKEND = value
