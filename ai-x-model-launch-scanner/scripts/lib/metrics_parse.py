"""Parse X engagement aria-labels into integer metrics. Locale-tolerant (EN + zh-CN)."""
from __future__ import annotations

import re
import sys

# Each metric: canonical key -> token alternatives (EN + zh). Number precedes the token.
_TOKENS = {
    "replies":   r"repl(?:y|ies)|回复",
    "reposts":   r"reposts?|转推|转发",
    "quotes":    r"quotes?|引用",
    "likes":     r"likes?|喜欢|赞",
    "bookmarks": r"bookmarks?|书签",
    "views":     r"views?|查看|浏览",
}
_NUM = r"([\d][\d,.\s]*[KkMmBb]?)"

_PATTERNS = {k: re.compile(_NUM + r"[\s条次个]*(?:" + v + r")", re.IGNORECASE)
             for k, v in _TOKENS.items()}


def _to_int(raw: str) -> int | None:
    s = raw.strip().replace(",", "").replace(" ", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([KkMmBb]?)", s)
    if not m:
        return None
    mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(m.group(2).lower(), 1)
    val = float(m.group(1)) * mult
    return int(round(val))


def parse_engagement(label: str | None) -> dict:
    """'81 replies, 328 reposts, 2448 likes, 215 bookmarks, 182331 views' -> ints.

    Unknown/missing keys are None. Handles 1,234 / 1.2K / 3M / zh labels."""
    out = {k: None for k in _TOKENS}
    if not label:
        return out
    for key, pat in _PATTERNS.items():
        m = pat.search(label)
        if not m:
            continue
        raw = m.group(1).strip()
        # decimal shorthand: 1.2K / 3.5M
        dec = re.fullmatch(r"([\d,.]+)\s*([KkMmBb])", raw)
        if dec and "." in dec.group(1):
            base = float(dec.group(1).replace(",", ""))
            mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[dec.group(2).upper()]
            out[key] = int(base * mult)
        else:
            out[key] = _to_int(raw)
    return out


def parse_slash_engagement(raw: str | None) -> dict:
    """'798/1754/14966/4084763' -> ints. Slash shorthand seen in 2026-09-04 hermes runs.

    4 parts = replies/reposts/likes/views; 5 parts = replies/reposts/likes/bookmarks/views
    (order confirmed by run 20260904-153150 snapshot p8: 4526/32131/188956/53987/44634662).
    Handles K/M suffix per part. Unknown parts -> None."""
    out = {k: None for k in _TOKENS}
    if not raw:
        return out
    parts = [p.strip() for p in str(raw).split("/") if p.strip()]
    if len(parts) not in (4, 5):
        return out
    keys = ["replies", "reposts", "likes", "views"] if len(parts) == 4 else \
           ["replies", "reposts", "likes", "bookmarks", "views"]
    for key, part in zip(keys, parts):
        out[key] = _to_int(part)
    return out


def selftest() -> None:
    m = parse_engagement("81 replies, 328 reposts, 2448 likes, 215 bookmarks, 182331 views")
    assert m == {"replies": 81, "reposts": 328, "quotes": None, "likes": 2448,
                 "bookmarks": 215, "views": 182331}, m
    m = parse_engagement("1.2K Likes    342 Reposts")
    assert m["likes"] == 1200 and m["reposts"] == 342, m
    m = parse_engagement("12,345 views")
    assert m["views"] == 12345, m
    m = parse_engagement("81 条回复, 328 次转推, 2448 次喜欢")
    assert m["replies"] == 81 and m["reposts"] == 328 and m["likes"] == 2448, m
    m = parse_engagement(None)
    assert all(v is None for v in m.values())
    m = parse_engagement("3 quotes")
    assert m["quotes"] == 3
    m = parse_slash_engagement("798/1754/14966/4084763")
    assert m == {"replies": 798, "reposts": 1754, "quotes": None, "likes": 14966,
                 "bookmarks": None, "views": 4084763}, m
    m = parse_slash_engagement("4526/32131/188956/53987/44634662")
    assert m["bookmarks"] == 53987 and m["views"] == 44634662, m
    m = parse_slash_engagement("4.4M/32K/189K/44634662")
    assert m["replies"] == 4_400_000 and m["reposts"] == 32_000, m
    m = parse_slash_engagement("a/b/c/d")
    assert all(v is None for v in m.values())
    print("metrics_parse selftest: all assertions passed")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--selftest" in sys.argv:
        selftest()
    else:
        import json
        print(json.dumps(parse_engagement(sys.argv[1] if len(sys.argv) > 1 else ""), ensure_ascii=False))
