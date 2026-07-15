"""Build GitHub Release body from the CURRENT version entry in app_update.json only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_history(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    hist = data.get("history")
    if isinstance(hist, list) and hist:
        return [x for x in hist if isinstance(x, dict)]
    ver = str(data.get("version") or "").strip()
    if ver:
        return [
            {
                "version": ver,
                "title": str(data.get("title") or ver),
                "body": str(data.get("body") or ""),
            }
        ]
    return []


def pick_entry(history: list[dict], version: str | None) -> dict | None:
    if not history:
        return None
    ver = (version or "").strip().lstrip("v")
    if ver:
        for item in history:
            item_ver = str(item.get("version") or "").strip().lstrip("v")
            if item_ver == ver:
                return item
    # Fallback: newest (history[0])
    return history[0]


def build_notes(history: list[dict], *, version: str | None = None) -> str:
    """Only the release version's title + body — never dump full history."""
    item = pick_entry(history, version)
    if not item:
        return "（无更新说明：请在 app_update.json 的 history 中填写本版本 title / body）\n"

    item_ver = str(item.get("version") or "").strip() or "?"
    title = str(item.get("title") or "").strip() or item_ver
    body = str(item.get("body") or "").strip()

    lines = [f"## {title}", ""]
    lines.append(body if body else "（本条未填写 body）")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Release notes for ONE version from app_update.json"
    )
    parser.add_argument(
        "--version",
        default="",
        help="Release version (required in CI; defaults to history[0])",
    )
    parser.add_argument("-o", "--output", default="", help="Write to file (default: stdout)")
    parser.add_argument(
        "--channel",
        default=str(ROOT / "app_update.json"),
        help="Path to app_update.json",
    )
    args = parser.parse_args()

    path = Path(args.channel)
    if not path.is_file():
        print(f"missing {path}", file=sys.stderr)
        return 1

    notes = build_notes(load_history(path), version=args.version or None)
    if args.output:
        out = Path(args.output)
        out.write_text(notes, encoding="utf-8")
        print(f"OK: wrote {out} ({len(notes)} chars)")
    else:
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass
        sys.stdout.buffer.write(notes.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
