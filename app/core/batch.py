"""Batch import (F2.4): pull every URL out of pasted text or a text file."""

from __future__ import annotations

import re

_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
#: Punctuation that is far more likely to trail a URL in prose than end one.
_TRAILING = ".,;:!?)]}'\""


def extract_urls(text: str) -> list[str]:
    """Every http(s) URL in ``text``, de-duplicated, in order of appearance."""
    urls: list[str] = []
    seen: set[str] = set()
    for match in _URL.findall(text):
        url = match.rstrip(_TRAILING)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls
