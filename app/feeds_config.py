from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).parent / "feeds.yaml"


@lru_cache(maxsize=1)
def load() -> dict:
    with CONFIG_PATH.open() as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("rss", [])
    cfg.setdefault("reddit", [])
    cfg.setdefault("keywords", [])
    cfg.setdefault("high_signal", [])
    cfg.setdefault("nvd_keywords", [])
    return cfg


def keywords() -> list[str]:
    return load()["keywords"]


def high_signal() -> set[str]:
    return {s.lower() for s in load()["high_signal"]}


def nvd_keywords() -> list[str]:
    return load()["nvd_keywords"]
