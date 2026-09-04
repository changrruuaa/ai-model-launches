"""notion_sync.py — Step 7 Notion writer (auto-create DB, idempotent upsert by Tweet ID).

  --check-auth                       verify NOTION_TOKEN (never printed)
  --base-dir D --run-id R --parent-id <32hex> [--database-id <id>] [--no-update]

Secrets: NOTION_TOKEN arrives via machine env var (setx + Hermes restart); NEVER printed or logged.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import models  # noqa: E402

DB_TITLE = "AI Model Launches"
PROPS = {
    "Name":       {"title": {}},
    "Tweet ID":   {"rich_text": {}},   # dedup key (IDs exceed JS safe integer, not number)
    "Company":    {"select": {}},
    "Author":     {"rich_text": {}},
    "Model Name": {"rich_text": {}},
    "URL":        {"url": {}},
    "Created At": {"date": {}},
    "Confidence": {"number": {"format": "percent"}},
    "Category":   {"select": {}},
    "Key Facts":  {"rich_text": {}},
    "Raw Text":   {"rich_text": {}},   # cap 1900 (Notion rich_text limit 2000)
    "Metrics":    {"rich_text": {}},
    "Scanned At": {"date": {}},
    "Status":     {"select": {}},      # new / reviewed / archived
    "Verified":   {"checkbox": {}},
}


def _client():
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        print("NOTION_TOKEN: missing (set machine env var: setx NOTION_TOKEN \"ntn_...\", then restart Hermes desktop)")
        raise SystemExit(3)
    from notion_client import Client
    return Client(auth=token)


def check_auth() -> int:
    nc = _client()
    me = nc.users.me()
    print(f"NOTION_TOKEN: ok (bot={me.get('name')})")
    return 0


def _rt(text, cap=1900):
    return {"rich_text": [{"type": "text", "text": {"content": (text or "")[:cap]}}]}


def _props(e: dict, scanned_at: str) -> dict:
    m = e.get("metrics") or {}
    metrics = ", ".join(f"{k}={v}" for k, v in m.items() if v is not None)
    return {
        "Name": {"title": [{"type": "text",
                            "text": {"content": e.get("one_line_cn") or e.get("model_name") or "（未命名）"}}]},
        "Tweet ID": _rt(e["id"], 64),
        "Company": {"select": {"name": e.get("company") or "未知"}},
        "Author": _rt(e.get("handle") or "", 64),
        "Model Name": _rt(e.get("model_name") or "", 1900),
        "URL": {"url": e.get("url")},
        "Created At": {"date": {"start": e["created_at"]}} if e.get("created_at") else None,
        "Confidence": {"number": round(float(e.get("confidence") or 0) * 100, 1)},
        "Category": {"select": {"name": e.get("category") or "other"}},
        "Key Facts": _rt(" · ".join(e.get("key_facts") or [])),
        "Raw Text": _rt(e.get("text") or ""),
        "Metrics": _rt(metrics),
        "Scanned At": {"date": {"start": scanned_at[:10]}},
        "Status": {"select": {"name": "new"}},
        "Verified": {"checkbox": bool(e.get("release_verified"))},
    }


def _with_retry(fn, tries=3):
    for n in range(tries):
        try:
            return fn()
        except Exception as e:  # notion-client APIResponseError w/ 429 or transient
            if n == tries - 1 or "429" not in str(e) and "Rate" not in str(e):
                raise
            time.sleep(2 ** n)


def sync(base_dir: str, run_id: str, parent_id: str, database_id: str | None,
         update_existing: bool) -> int:
    nc = _client()
    rd = models.raw_dir(base_dir, run_id)
    report = models.load_run_report(base_dir, run_id)
    cc = models.read_json(rd / "cross_checked.json")
    scanned_at = report["created_at"]

    if not database_id:
        database_id = nc.databases.create(
            parent={"type": "page_id", "page_id": parent_id},
            title=[{"type": "text", "text": {"content": DB_TITLE}}],
            properties=PROPS)["id"]
        print(f"database created: {database_id}")
        report["database_id"] = database_id

    entries = cc["launches"] + cc["signals"]
    created = updated = skipped = 0
    for e in entries:
        props = _props(e, scanned_at)
        props = {k: v for k, v in props.items() if v is not None}
        q = nc.databases.query(database_id=database_id,
                               filter={"property": "Tweet ID",
                                       "rich_text": {"equals": e["id"]}},
                               page_size=1)
        time.sleep(0.35)  # Notion rate limit ~3 rps
        if q["results"]:
            if not update_existing:
                skipped += 1
                continue
            pid = q["results"][0]["id"]
            _with_retry(lambda: nc.pages.update(
                page_id=pid,
                properties={k: props[k] for k in
                            ("Metrics", "Confidence", "Key Facts", "Verified") if k in props}))
            updated += 1
        else:
            children = []
            if e.get("text"):
                children.append({"object": "block", "type": "paragraph",
                                 "paragraph": {"rich_text": [{"type": "text",
                                              "text": {"content": e["text"][:1900]}}]}})
            if e.get("url"):
                children.append({"object": "block", "type": "bookmark",
                                 "bookmark": {"url": e["url"]}})
            _with_retry(lambda: nc.pages.create(parent={"database_id": database_id},
                                                properties=props, children=children))
            created += 1

    report["stages"]["notion"] = {"created": created, "updated": updated,
                                  "skipped": skipped, "database_id": database_id,
                                  "at": models.now_cst().isoformat(timespec="seconds")}
    models.save_run_report(base_dir, run_id, report)
    print(f"notion: created={created} updated={updated} skipped={skipped} db={database_id}")
    return 0


def main() -> int:
    models.ensure_utf8_stdout()
    p = argparse.ArgumentParser()
    p.add_argument("--check-auth", action="store_true")
    p.add_argument("--base-dir", default=None)
    p.add_argument("--run-id", default=None)
    p.add_argument("--parent-id", default=None, help="parent page id (32 hex)")
    p.add_argument("--database-id", default=None)
    p.add_argument("--no-update", action="store_true", help="skip existing Tweet IDs")
    args = p.parse_args()

    if args.check_auth:
        raise SystemExit(check_auth())
    if not (args.base_dir and args.run_id and args.parent_id):
        print("--parent-id required (from skills.config.notion_parent_page_id)")
        return 2
    raise SystemExit(sync(args.base_dir, args.run_id, args.parent_id,
                          args.database_id, update_existing=not args.no_update))


if __name__ == "__main__":
    raise SystemExit(main())
