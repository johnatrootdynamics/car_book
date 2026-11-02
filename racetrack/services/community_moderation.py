"""Small, deterministic safety layer for public community text.

This is intentionally conservative: it blocks clear threats, targeted abuse,
sexual solicitation, and common spam patterns while leaving ordinary track-day
conversation alone. User reports remain available for context a text filter
cannot understand, especially uploaded images.
"""

import re
import unicodedata


_BLOCKED_PATTERNS = (
    re.compile(r"\b(?:kill|shoot|stab|hurt)\s+(?:you|yourself|them|him|her)\b", re.I),
    re.compile(r"\b(?:go\s+die|kys|bomb\s+threat)\b", re.I),
    re.compile(r"\b(?:send|trade|buy|sell)\s+(?:nudes?|explicit\s+photos?)\b", re.I),
    re.compile(r"\b(?:child\s+porn|revenge\s+porn)\b", re.I),
    re.compile(r"\b(?:n[i1]gg(?:er|a)|f[a@]ggot|k[i1]ke|ch[i1]nk)\b", re.I),
)
_URL_PATTERN = re.compile(r"https?://|www\.", re.I)
_REPEATED_TOKEN = re.compile(r"\b([a-z0-9]{4,})\b(?:\s+\1\b){4,}", re.I)


def normalized_text(value):
    value = unicodedata.normalize("NFKC", value or "")
    return " ".join(value.split())


def community_text_error(value):
    """Return a user-safe rejection reason, or ``None`` when text can publish."""

    text = normalized_text(value)
    if not text:
        return None
    if any(pattern.search(text) for pattern in _BLOCKED_PATTERNS):
        return "That text violates the Track Ops Community Guidelines."
    if len(_URL_PATTERN.findall(text)) > 2 or _REPEATED_TOKEN.search(text):
        return "That text looks like spam. Remove repeated links or text and try again."
    return None
