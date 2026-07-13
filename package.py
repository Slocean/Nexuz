#!/usr/bin/env python3
"""
Nexuz one-click package script (Windows).

Steps:
  1) npm run build  → frontend/dist
  2) PyInstaller    → dist/Nexuz.exe  (default: single-file)

Usage (from repo root):
  python package.py
  python package.py --skip-frontend
  python package.py --onedir
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"
DIST_UI = FRONTEND / "dist" / "index.html"
OUT_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(cwd or ROOT))


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        run([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0"])


def build_frontend() -> None:
    if not (FRONTEND / "package.json").exists():
        raise SystemExit(f"missing frontend: {FRONTEND}")
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("npm not found — install Node.js 18+")
    if not (FRONTEND / "node_modules").exists():
        run([npm, "install"], cwd=FRONTEND)
    run([npm, "run", "build"], cwd=FRONTEND)
    if not DIST_UI.exists():
        raise SystemExit("frontend build failed: frontend/dist/index.html missing")


def collect_datas() -> list[tuple[str, str]]:
    """(src, dest_inside_bundle) pairs for PyInstaller --add-data."""
    sep = ";" if os.name == "nt" else ":"
    pairs: list[tuple[str, str]] = []

    def add(src: Path, dest: str) -> None:
        if not src.exists():
            print(f"! skip missing data: {src}")
            return
        pairs.append((str(src), dest))

    add(FRONTEND / "dist", "frontend/dist")
    add(ROOT / "schemas", "schemas")
    add(
        ROOT / "backend" / "core" / "input" / "frida" / "scripts",
        "backend/core/input/frida/scripts",
    )
    # Keep examples optional for first-run demos
    add(ROOT / "examples", "examples")
    return pairs


def build_exe(*, onefile: bool) -> None:
    ensure_pyinstaller()
    datas = collect_datas()
    if not any(d[1].startswith("frontend/dist") for d in datas):
        raise SystemExit("frontend/dist not found — run without --skip-frontend")

    # Clean previous bundle output (keep other files under dist/)
    target_name = "Nexuz"
    if onefile:
        out_exe = OUT_DIR / f"{target_name}.exe"
        if out_exe.exists():
            out_exe.unlink()
    else:
        bundle = OUT_DIR / target_name
        if bundle.exists():
            shutil.rmtree(bundle)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        target_name,
        "--windowed",  # no console
        f"--distpath={OUT_DIR}",
        f"--workpath={BUILD_DIR / 'pyinstaller'}",
        f"--specpath={BUILD_DIR}",
        "--paths",
        str(ROOT),
        "--collect-submodules",
        "backend",
        "--collect-all",
        "rapidocr_onnxruntime",
        "--collect-all",
        "onnxruntime",
        "--collect-all",
        "webview",
        "--hidden-import",
        "clr",
        "--hidden-import",
        "pythonnet",
    ]

    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    sep = ";" if os.name == "nt" else ":"
    for src, dest in datas:
        cmd += ["--add-data", f"{src}{sep}{dest}"]

    # Entry: run backend.main as a script path so PyInstaller traces imports
    entry = ROOT / "backend" / "main.py"
    cmd.append(str(entry))

    run(cmd)

    if onefile:
        print(f"\nOK: {OUT_DIR / (target_name + '.exe')}")
    else:
        print(f"\nOK: {OUT_DIR / target_name / (target_name + '.exe')}")
        print("  (onedir — keep the whole folder together)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Nexuz desktop package")
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="Skip npm run build (use existing frontend/dist)",
    )
    parser.add_argument(
        "--onedir",
        action="store_true",
        help="Folder bundle (exe + _internal); default is single-file exe",
    )
    args = parser.parse_args()

    if sys.platform != "win32":
        print("warning: packaging is intended for Windows (WebView2)")

    if not args.skip_frontend:
        build_frontend()
    elif not DIST_UI.exists():
        raise SystemExit("frontend/dist missing — remove --skip-frontend")

    build_exe(onefile=not bool(args.onedir))


if __name__ == "__main__":
    main()
