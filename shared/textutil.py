"""Small text helpers to tame a 270M model's output."""

import re

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF←-⇿⬀-⯿]"
)


def strip_emojis(s: str) -> str:
    return _EMOJI.sub("", s).strip()


def first_line(s: str) -> str:
    for ln in s.splitlines():
        if ln.strip():
            return ln.strip().strip('"').strip()
    return ""


def _has_letter(s: str) -> bool:
    return bool(re.search(r"[a-zA-ZáéíóúñÁÉÍÓÚÑ]", s))


def short_lines(s: str, n: int = 3) -> list:
    """Return up to n clean short lines; if the model wrote one prose blob, split
    it. Drops markdown noise lines (e.g. '**', ':') with no real words."""
    lines = [ln.strip(" -•*#\t").strip() for ln in s.splitlines() if ln.strip()]
    lines = [ln for ln in lines if _has_letter(ln)]
    if len(lines) < 2:
        parts = re.split(r"[.,;:]\s+", s.strip())
        lines = [p.strip(" -•*#\t").strip() for p in parts if _has_letter(p)]
    return lines[:n]
