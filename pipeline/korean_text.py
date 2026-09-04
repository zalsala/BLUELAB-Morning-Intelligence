"""Small deterministic helpers for Korean postposition selection."""
from __future__ import annotations

import re

_HANGUL_BASE = 0xAC00
_HANGUL_END = 0xD7A3


def _last_meaningful_char(text: str) -> str:
    """Return the last Hangul syllable/alphanumeric character, ignoring punctuation."""
    for ch in reversed((text or "").strip()):
        if "가" <= ch <= "힣" or ch.isalnum():
            return ch
    return ""


def has_final_consonant(text: str) -> bool:
    """Return whether the final Korean syllable has jongseong.

    Non-Hangul endings are treated conservatively as no final consonant because
    Korean readings of acronyms/numbers are context-dependent.
    """
    ch = _last_meaningful_char(text)
    if not ch:
        return False
    code = ord(ch)
    if not (_HANGUL_BASE <= code <= _HANGUL_END):
        return False
    return (code - _HANGUL_BASE) % 28 != 0


def object_particle(text: str) -> str:
    """Return 을 after a final consonant, otherwise 를."""
    return "을" if has_final_consonant(text) else "를"


def append_object_particle(text: str) -> str:
    return f"{text}{object_particle(text)}"
