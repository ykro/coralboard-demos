"""Gemma 3 270M text generation.

Backend is chosen by config.BACKEND (NOT by the hardware MOCK flag), so the
laptop `--mock` demo and the board run use the SAME real model:

  "gguf"     -> Gemma 3 270M GGUF via llama.cpp (laptop + board CPU). Default.
  "template" -> rule-based stand-in (no model; fast offline fallback).

The GGUF is built from Google's official google/gemma-3-270m weights (see
models/README.md). Running it on the NPU via Synaptics Torq is an optional
speed/efficiency optimization, documented in models/README.md.

Gemma 3 270M is text-only; vision is handled separately (see vision_labels).
"""

import threading

from . import config

# llama.cpp's context is NOT reentrant: calling the same Llama instance from two
# threads at once (e.g. the web chat box on the server thread while the main loop
# regenerates the greeting) segfaults. Serialize every model call through one lock.
# The board only has 2 A55 cores anyway, so there's nothing to gain from parallel
# inference; the chat just waits (showing "thinking...") if a greeting is in flight.
_llm_lock = threading.Lock()


def generate(prompt: str, max_tokens: int = 96, temperature: float = 0.9) -> str:
    """Chat-style generation (instruction following)."""
    if config.BACKEND == "template":
        return _template_generate(prompt)
    with _llm_lock:
        out = _ensure_llm().create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens, temperature=temperature,
        )
    return out["choices"][0]["message"]["content"].strip()


def complete(prompt: str, max_tokens: int = 64, temperature: float = 0.8, stop=None) -> str:
    """Raw text completion — best for few-shot prompts, since it CONTINUES the
    pattern instead of answering conversationally (no 'Sure! Here is...')."""
    if config.BACKEND == "template":
        return _template_generate(prompt)
    with _llm_lock:
        out = _ensure_llm().create_completion(
            prompt=prompt, max_tokens=max_tokens, temperature=temperature, stop=stop or [],
        )
    return out["choices"][0]["text"].strip()


# --- gguf: Gemma 3 270M via llama.cpp (laptop + board CPU) ------------------

_llm = None


def _ensure_llm():
    global _llm
    if _llm is None:
        try:
            from llama_cpp import Llama
        except ImportError as e:
            raise RuntimeError(
                "llama-cpp-python not installed. Laptop: use ./.venv (see README). "
                "Board: run setup_board.sh. Or set CORAL_BACKEND=template."
            ) from e
        _llm = Llama(
            model_path=config.MODEL_PATH,
            n_ctx=2048,
            n_threads=2,          # 2x Cortex-A55 on the board
            verbose=False,
            chat_format="gemma",
        )
    return _llm


# --- template: no-model fallback -------------------------------------------

def _template_generate(prompt: str) -> str:
    p = prompt.lower()
    if "haiku" in p or "poem" in p:
        labels = _labels_from_prompt(prompt)
        subject = labels[0] if labels else "the light"
        return f"{subject.capitalize()} in silence,\nthe afternoon turns to verse,\nbreathe in the moment."
    return "..."


def _labels_from_prompt(prompt: str):
    if "about" in prompt:
        tail = prompt.split("about", 1)[1].strip().strip(".:").strip()
        return [t.strip() for t in tail.replace(" and ", ", ").split(",") if t.strip()]
    return []
