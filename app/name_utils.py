"""Canonical player-name normalization, shared by anything that compares or
joins player names across data sources (Sleeper, The Odds API, FantasyPros)
or resolves a name typed by a person (the Ask assistant).

Kept in one place instead of re-implemented per source: two independent
copies of "strip a suffix" already drifted once during this project.
"""
import re

_SUFFIX_RE = re.compile(r"\s+(jr|sr|ii|iii|iv|v)$", re.IGNORECASE)
_STRIP_CHARS_RE = re.compile(r"[.,']")
_SPACE_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Lowercases, drops periods/commas/apostrophes, turns hyphens into
    spaces, strips a trailing generational suffix, and collapses whitespace.

    "Kenneth Walker III" and "kenneth walker" both normalize to
    "kenneth walker"; "A.J. Brown" and "AJ Brown" both normalize to
    "aj brown".
    """
    if not name:
        return ""
    n = name.lower().replace("-", " ")
    n = _STRIP_CHARS_RE.sub("", n)
    n = _SPACE_RE.sub(" ", n).strip()
    n = _SUFFIX_RE.sub("", n).strip()
    return n
