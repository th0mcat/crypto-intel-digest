"""Offline sanity check for the pure logic: entity extraction, hashing,
triage scoring, and digest formatting. No network, no DB. Run inside the
image: `docker run --rm ... python scripts/selftest.py`.
"""
import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "x")
os.environ.setdefault("TELEGRAM_OPERATOR_ID", "1")
os.environ.setdefault("DATABASE_URL", "postgresql://x@x/x")

from app.feeds_config import high_signal, keywords  # noqa: E402
from app.models import Event  # noqa: E402
from app.normalise import extract_entities  # noqa: E402
from app import triage  # noqa: E402

failures = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        failures.append(name)


# --- entity extraction ---
ents = extract_entities(
    "OpenSSL CVE-2024-1234 exploit lets attackers do $ETH key recovery",
    keywords(),
)
kinds = {e["type"] for e in ents}
values = {e["value"] for e in ents}
check("extracts CVE id", "CVE-2024-1234" in values)
check("extracts ticker", "ETH" in values)
check("extracts keyword", "exploit" in values)
check("has three kinds", {"cve", "ticker", "keyword"} <= kinds)

# --- hashing / dedup ---
a = Event(source="rss:x", source_type="rss", title="Big hack", url="http://a/1")
b = Event(source="rss:x", source_type="rss", title="Big hack", url="http://a/1")
c = Event(source="rss:x", source_type="rss", title="Big hack", url="http://a/2")
check("identical items share raw_hash", a.raw_hash == b.raw_hash)
check("different url -> different raw_hash", a.raw_hash != c.raw_hash)
check("same title -> same title_hash", a.title_hash == c.title_hash)

# --- triage: material, novel, specific beats bland ---
hs = high_signal()
hot = Event(
    source="rss:sec-press",
    source_type="rss",
    title="OpenSSL zero-day exploit enables key recovery",
    url="http://sec/1",
    raw_text="x" * 400,
    entities=extract_entities("OpenSSL zero-day exploit key recovery", keywords()),
    source_reputation=0.85,
)
bland = Event(
    source="reddit:CryptoCurrency",
    source_type="reddit",
    title="gm everyone what coin today",
    url="",
    raw_text="short",
    entities=[],
    source_reputation=0.3,
)
hot_score, hot_reasons = triage.score(hot, is_novel=True, high_signal=hs)
bland_score, _ = triage.score(bland, is_novel=True, high_signal=hs)
check(f"hot item scores high ({hot_score:.2f})", hot_score >= 0.6)
check(f"bland item scores low ({bland_score:.2f})", bland_score < 0.45)
check("hot outscores bland", hot_score > bland_score)
check("reasons are populated", len(hot_reasons) >= 2)

# --- novelty penalty applies ---
repeat_score, _ = triage.score(hot, is_novel=False, high_signal=hs)
check("repeat scores lower than novel", repeat_score < hot_score)

print()
if failures:
    raise SystemExit(f"{len(failures)} check(s) failed: {failures}")
print("all self-tests passed")
