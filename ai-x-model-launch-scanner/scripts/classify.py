"""classify.py — Step 4a LLM classification (inline dry-run / --api dual mode).

Modes:
  python classify.py --base-dir D --run-id R                 build to_classify.json (agent classifies inline)
  python classify.py ... --slice 50                          split to_classify into parts for chunked inline
  python classify.py ... --merge                             merge classified.part*.json -> classified.json
  python classify.py ... --validate [--file F]               schema-check a classified.json (default: run dir)
  python classify.py ... --api                               script calls claude-haiku-4-5 (unattended)

>120 entries: SKILL.md hard rule is to use --api (context protection). --slice is the contingency.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import models  # noqa: E402

MODEL = "claude-haiku-4-5"
BATCH_SIZE = 15
MAX_TEXT = 4000
INLINE_THRESHOLD = 120
CATEGORIES = ["model_release", "capability_update", "benchmark", "research_paper",
              "product", "other"]
MIN_CONFIDENCE = 0.6

CLASSIFY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["results"],
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "is_launch", "confidence", "category", "key_facts", "one_line_cn"],
                "properties": {
                    "id": {"type": "string"},
                    "is_launch": {"type": "boolean"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "model_name": {"type": ["string", "null"]},
                    "company": {"type": "string"},
                    "category": {"enum": CATEGORIES},
                    "key_facts": {"type": "array", "items": {"type": "string"}},
                    "one_line_cn": {"type": "string"},
                },
            },
        }
    },
}


def prompt_text() -> str:
    return (models.SKILL_DIR / "templates" / "classify_prompt.txt").read_text(encoding="utf-8")


def build_to_classify(rd: Path) -> list[dict]:
    cand = models.read_json(rd / "candidates.json")
    try:
        details = models.read_json(rd / "detail_tweets.json")
    except FileNotFoundError:
        details = {}

    entries = []
    for t in cand["candidates"]:
        d = details.get(t["id"], {})
        entries.append({
            "id": t["id"], "handle": t.get("handle", ""), "company": d.get("company") or t.get("company", ""),
            "text": (d.get("full_text_long") or t["text"])[:MAX_TEXT],
            "url": t["url"], "is_third_party": False, "is_pinned": t.get("is_pinned", False),
        })
    for t in cand["thirdparty"]:
        entries.append({
            "id": t["id"], "handle": t.get("handle", ""), "company": t.get("company", ""),
            "text": t["text"][:MAX_TEXT], "url": t["url"], "is_third_party": True,
            "is_pinned": t.get("is_pinned", False),
        })
    return entries


def validate_entries(items: list[dict]) -> list[str]:
    errs = []
    for i, it in enumerate(items):
        if "id" not in it:
            errs.append(f"[{i}] missing id")
            continue
        if not isinstance(it.get("is_launch"), bool):
            errs.append(f"[{it['id']}] is_launch must be boolean")
        c = it.get("confidence")
        if not isinstance(c, (int, float)) or not 0 <= c <= 1:
            errs.append(f"[{it['id']}] confidence must be 0..1")
        if it.get("category") not in CATEGORIES:
            errs.append(f"[{it['id']}] category '{it.get('category')}' not allowed")
        if c is not None and isinstance(c, (int, float)) and c < MIN_CONFIDENCE and it.get("is_launch"):
            errs.append(f"[{it['id']}] confidence<{MIN_CONFIDENCE} but is_launch=true")
        if not isinstance(it.get("key_facts"), list):
            errs.append(f"[{it['id']}] key_facts must be list")
        if not it.get("one_line_cn"):
            errs.append(f"[{it['id']}] one_line_cn empty")
    return errs


def run_api(entries: list[dict], rd: Path) -> dict:
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic SDK not installed -> python -m pip install anthropic")
        raise SystemExit(4)
    system = prompt_text()
    client = anthropic.Anthropic()
    results: list[dict] = []
    for i in range(0, len(entries), BATCH_SIZE):
        chunk = entries[i:i + BATCH_SIZE]
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2048 * ((len(chunk) // 10) + 1),
            system=system,
            messages=[{"role": "user",
                       "content": json.dumps(chunk, ensure_ascii=False)}],
            output_config={"format": {"type": "json_schema", "schema": CLASSIFY_SCHEMA}},
        )
        payload = json.loads("".join(b.text for b in resp.content if b.type == "text"))
        results.extend(payload["results"])
        print(f"  batch {i // BATCH_SIZE + 1}: {len(chunk)} tweets, "
              f"in={resp.usage.input_tokens} out={resp.usage.output_tokens}")
    out = {"classified_at": models.now_cst().isoformat(timespec="seconds"),
           "model": MODEL, "items": results}
    models.write_json(rd / "classified.json", out)
    return out


def main() -> int:
    models.ensure_utf8_stdout()
    p = argparse.ArgumentParser()
    p.add_argument("--base-dir", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--api", action="store_true")
    p.add_argument("--slice", type=int, default=None, metavar="N")
    p.add_argument("--merge", action="store_true")
    p.add_argument("--validate", action="store_true")
    p.add_argument("--file", default=None, help="validate target (default <run>/classified.json)")
    args = p.parse_args()

    rd = models.raw_dir(args.base_dir, args.run_id)

    if args.validate:
        target = Path(args.file) if args.file else rd / "classified.json"
        data = models.read_json(target)
        errs = validate_entries(data["items"])
        if errs:
            print(f"VALIDATE-ERRORS ({len(errs)}):")
            for e in errs[:15]:
                print(f"  - {e}")
            return 2
        n = len(data["items"])
        launches = sum(1 for x in data["items"] if x["is_launch"])
        print(f"validate ok: {n} entries, launches={launches}")
        return 0

    if args.merge:
        items = []
        for f in sorted(rd.glob("classified.part*.json")):
            items.extend(models.read_json(f)["items"])
        models.write_json(rd / "classified.json",
                          {"classified_at": models.now_cst().isoformat(timespec="seconds"),
                           "model": "inline-merged", "items": items})
        errs = validate_entries(items)
        print(f"merged {len(items)} entries; validation errors={len(errs)}")
        return 2 if errs else 0

    entries = build_to_classify(rd)
    report = models.load_run_report(args.base_dir, args.run_id)

    if args.api:
        out = run_api(entries, rd)
        report["stages"]["classify"] = {"mode": "api", "model": MODEL, "items": len(out["items"]),
                                        "at": models.now_cst().isoformat(timespec="seconds")}
        models.save_run_report(args.base_dir, args.run_id, report)
        print(f"classified (api): {len(out['items'])} entries")
        return 0

    models.write_json(rd / "to_classify.json", entries)
    if args.slice:
        n = max(1, args.slice)
        parts = [entries[i:i + n] for i in range(0, len(entries), n)]
        for k, part in enumerate(parts, 1):
            models.write_json(rd / f"to_classify.part{k:02d}.json", part)
        print(f"to_classify: {len(entries)} entries in {len(parts)} parts of <= {n}")
    else:
        hint = (" -> use --api (context protection rule)" if len(entries) > INLINE_THRESHOLD else
                " -> inline classification (agent reads this file, writes classified.json, then --validate)")
        print(f"to_classify: {len(entries)} entries{hint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
