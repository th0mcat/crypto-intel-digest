"""Entity extraction. Deliberately naive for Phase 1 — regex + a keyword
watchlist. Phase 3's entity store (aliases, resolution) replaces this. All
inputs here are untrusted scraped text and are only ever pattern-matched,
never interpreted as instructions.
"""
import re

CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
CASHTAG_RE = re.compile(r"(?<![A-Za-z0-9])\$([A-Z]{2,6})\b")


def extract_entities(text: str, keywords: list[str]) -> list[dict]:
    if not text:
        return []
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, value: str) -> None:
        key = (kind, value.lower())
        if key not in seen:
            seen.add(key)
            found.append({"type": kind, "value": value})

    for m in CVE_RE.findall(text):
        add("cve", m.upper())
    for m in CASHTAG_RE.findall(text):
        add("ticker", m.upper())

    lowered = text.lower()
    for kw in keywords:
        if kw.lower() in lowered:
            add("keyword", kw)
    return found
