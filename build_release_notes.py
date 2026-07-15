"""Build GitHub Release body markdown from app_update.json history."""

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
    # legacy single entry
    ver = str(data.get("version") or "").strip()
    if ver:
        return [
            {
                "version": ver,
                "title": str(data.get("title") or f"{ver}"),
                "body": str(data.get("body") or ""),
            }
        ]
    return []


def build_notes(history: list[dict], *, version: str | None = None) -> str:
    """Full history (newest first). If version is set, put that entry first and keep the rest."""
    if not history:
        return "（无更新说明：请在 app_update.json 的 history 中填写 title / body）\n"

    ver = (version or "").strip().lstrip("v")
    lines: list[str] = []

    # Prefer matching entry at top when version given
    ordered = list(history)
    if ver:
        match = None
        rest = []
        for item in ordered:
            item_ver = str(item.get("version") or "").strip().lstrip("v")
            if match is None and item_ver == ver:
                match = item
            else:
                rest.append(item)
        if match is not None:
            ordered = [match, *rest]

    for i, item in enumerate(ordered):
        item_ver = str(item.get("version") or "").strip() or "?"
        title = str(item.get("title") or "").strip() or f"{item_ver}"
        body = str(item.get("body") or "").strip()
        if i == 0:
            lines.append(f"## {title}")
        else:
            lines.append(f"### {title}")
        lines.append("")
        if body:
            lines.append(body)
        else:
            lines.append("（本条未填写 body）")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Release notes from app_update.json")
    parser.add_argument(
        "--version",
        default="",
        help="Current release version (optional; used to order matching entry first)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="",
        help="Write to file (default: stdout)",
    )
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
