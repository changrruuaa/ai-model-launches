"""check_env.py — Step 0 dependency probe. Exit 0 = ready; exit 12 = missing deps."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import models  # noqa: E402

REQUIRED = [("yaml", "pyyaml"), ("jinja2", "jinja2"), ("requests", "requests"),
            ("dateutil", "python-dateutil")]
OPTIONAL = [("notion_client", "notion-client (Notion enabled)"),
            ("anthropic", "anthropic (classify --api)")]


def main() -> int:
    models.ensure_utf8_stdout()
    missing = []
    for mod, pip_name in REQUIRED:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(pip_name)
    optional_state = {}
    for mod, pip_name in OPTIONAL:
        try:
            importlib.import_module(mod)
            optional_state[pip_name] = "ok"
        except ImportError:
            optional_state[pip_name] = "missing"
    print(json.dumps({
        "python": sys.version.split()[0],
        "missing_required": missing,
        "optional": optional_state,
    }, ensure_ascii=False))
    if missing:
        print("install: python -m pip install " + " ".join(missing))
        return 12
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
