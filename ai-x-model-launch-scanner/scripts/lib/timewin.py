"""Time window computation (Asia/Shanghai) and X timestamp parsing."""
from __future__ import annotations

import email.utils
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CST = ZoneInfo("Asia/Shanghai")


def now_cst() -> datetime:
    return datetime.now(CST)


def window(days: int | None = None, since: str | None = None, until: str | None = None,
           now: datetime | None = None) -> tuple[datetime, datetime]:
    """Default window: until = now (CST), since = today-00:00 minus (days-1) days  => 近 N 自然日."""
    until_dt = datetime.fromisoformat(until) if until else (now or now_cst())
    until_dt = until_dt.astimezone(CST)
    if since:
        since_dt = datetime.fromisoformat(since).astimezone(CST)
    else:
        d = days or 7
        midnight = until_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        since_dt = midnight - timedelta(days=d - 1)
    return since_dt, until_dt


def parse_x_time(raw: str) -> datetime:
    """Parse X created_at like 'Wed Sep 03 10:12:33 +0000 2026' -> aware datetime in CST."""
    dt = email.utils.parsedate_to_datetime(raw)
    if dt is None:
        raise ValueError(f"unparseable X timestamp: {raw!r}")
    return dt.astimezone(CST)


import re as _re

_DISPLAY_DT = _re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::(\d{2}))?\s*(UTC|GMT|\+00:?00)?", _re.IGNORECASE)


def parse_display_time(raw: str) -> datetime:
    """Parse a human display string containing an absolute UTC datetime,
    e.g. '11h ago / 2026-09-04 03:32 UTC' (run 20260904-153150 format).
    Minute precision (relative part like '11h ago' is ignored). -> aware datetime in CST."""
    m = _DISPLAY_DT.search(raw or "")
    if not m:
        raise ValueError(f"no absolute datetime in display string: {raw!r}")
    date, hm, sec, _tz = m.groups()
    iso = f"{date}T{hm}:{sec or '00'}+00:00"
    return datetime.fromisoformat(iso).astimezone(CST)


def in_window(dt: datetime, win: tuple[datetime, datetime]) -> bool:
    since_dt, until_dt = win
    return since_dt <= dt <= until_dt


def selftest() -> None:
    # days=1 boundary: window is today's midnight..now
    ref = datetime(2026, 9, 4, 9, 30, tzinfo=CST)
    s, u = window(days=1, now=ref)
    assert s == datetime(2026, 9, 4, 0, 0, tzinfo=CST), s
    assert u == ref

    # days=7: since = 2026-08-29 00:00 CST
    s, u = window(days=7, now=ref)
    assert s == datetime(2026, 8, 29, 0, 0, tzinfo=CST), s

    # month boundary (Aug -> Sep)
    ref2 = datetime(2026, 9, 2, 23, 0, tzinfo=CST)
    s, _ = window(days=3, now=ref2)
    assert s == datetime(2026, 8, 31, 0, 0, tzinfo=CST), s

    # year boundary (2027 -> 2026)
    ref3 = datetime(2027, 1, 2, 12, 0, tzinfo=CST)
    s, _ = window(days=3, now=ref3)
    assert s == datetime(2026, 12, 31, 0, 0, tzinfo=CST), s

    # explicit since/until override, mixed timezone offsets
    s, u = window(since="2026-09-01T00:00:00+08:00", until="2026-09-04T23:59:59+08:00")
    assert s.day == 1 and u.day == 4

    # X timestamp parsing: UTC -> CST (+8)
    dt = parse_x_time("Wed Sep 03 10:12:33 +0000 2026")
    assert dt == datetime(2026, 9, 3, 18, 12, 33, tzinfo=CST), dt

    # display-string parsing (2026-09-04 hermes run format), minute precision
    dt2 = parse_display_time("11h ago / 2026-09-04 03:32 UTC")
    assert dt2 == datetime(2026, 9, 4, 11, 32, tzinfo=CST), dt2
    dt3 = parse_display_time("2026-08-14 09:00 UTC")
    assert dt3 == datetime(2026, 8, 14, 17, 0, tzinfo=CST), dt3

    # in_window inclusive bounds
    w = window(days=7, now=ref)
    assert in_window(parse_x_time("Fri Aug 28 16:00:00 +0000 2026"), w)   # 2026-08-29 00:00 CST
    assert not in_window(parse_x_time("Fri Aug 28 15:59:00 +0000 2026"), w)
    assert in_window(ref, w)

    print("timewin selftest: all assertions passed")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--selftest" in sys.argv:
        selftest()
    else:
        s, u = window(days=int(sys.argv[1]) if len(sys.argv) > 1 else 7)
        print(f"since={s.isoformat()} until={u.isoformat()}")
