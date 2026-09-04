"""Load vendors.*.json asset files (relative to skill dir, never absolute)."""
from __future__ import annotations

import random
from pathlib import Path

from .models import SKILL_DIR, read_json


def load(stage: str) -> list[dict]:
    """stage: 'main' | 'thirdparty' -> [{handle, company}, ...]"""
    path = SKILL_DIR / "assets" / f"vendors.{stage}.json"
    data = read_json(path)
    return [{"handle": a["handle"], "company": a["company"]} for a in data["accounts"]]


def shuffled(accounts: list[dict], rng: random.Random | None = None) -> list[dict]:
    """Anti-fingerprint: random scan order each run."""
    out = list(accounts)
    (rng or random).shuffle(out)
    return out
