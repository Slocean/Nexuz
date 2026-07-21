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
  python package.py --version 0.1.1
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
ICON_ICO = ROOT / "logo.ico"


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(cwd or ROOT))


def _install_locked_deps() -> None:
    """Install production lockfile (hashes required). Used for first-time package."""
    req = ROOT / "requirements.txt"
    if not req.is_file():
        raise SystemExit(f"缺少依赖锁文件: {req}")
    print(f"正在安装打包依赖（{req.name}，require-hashes）…")
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--require-hashes",
            "-r",
            str(req),
        ]
    )


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        _install_locked_deps()
        try:
            import PyInstaller  # noqa: F401
        except ImportError as exc:
            raise SystemExit(
                "已安装 requirements.txt 但仍无法导入 PyInstaller，"
                f"请确认当前解释器为 {sys.executable}"
            ) from exc


def ensure_pillow() -> None:
    try:
        import PIL  # noqa: F401
    except ImportError:
        _install_locked_deps()
        try:
            import PIL  # noqa: F401
        except ImportError as exc:
            raise SystemExit(
                "已安装 requirements.txt 但仍无法导入 Pillow，"
                f"请确认当前解释器为 {sys.executable}"
            ) from exc


def ensure_app_icon(*, force: bool = False) -> Path:
    """Build Windows .ico from logo.png for the exe + taskbar icon."""
    src = ROOT / "logo.png"
    if not src.exists():
        raise SystemExit("missing logo.png - cannot set exe icon")

    if (
        not force
        and ICON_ICO.exists()
        and ICON_ICO.stat().st_mtime >= src.stat().st_mtime
    ):
        return ICON_ICO

    ensure_pillow()
    from PIL import Image

    img = Image.open(src).convert("RGBA")
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)

    # Fit onto a square canvas so Windows icon sizes stay consistent
    side = max(img.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)

    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    square.save(ICON_ICO, format="ICO", sizes=sizes)
    print(f"OK: wrote {ICON_ICO} from {src.name} ({ICON_ICO.stat().st_size} bytes)")
    return ICON_ICO


def build_frontend() -> None:
    if not (FRONTEND / "package.json").exists():
        raise SystemExit(f"missing frontend: {FRONTEND}")
    # Keep UI logo in sync with repo root logo.png
    public_logo = FRONTEND / "public" / "logo.png"
    root_logo = ROOT / "logo.png"
    if root_logo.exists():
        public_logo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root_logo, public_logo)
        print(f"OK: synced {public_logo}")
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("npm not found - install Node.js 18+")
    if not (FRONTEND / "node_modules").exists():
        run([npm, "ci"], cwd=FRONTEND)
    run([npm, "run", "build"], cwd=FRONTEND)
    if not DIST_UI.exists():
        raise SystemExit("frontend build failed: frontend/dist/index.html missing")
    dist_logo = FRONTEND / "dist" / "logo.png"
    if root_logo.exists() and not dist_logo.exists():
        shutil.copy2(root_logo, dist_logo)


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
    add(ROOT / "app_update.json", ".")
    add(ROOT / "logo.ico", ".")
    add(ROOT / "logo.png", ".")
    add(
        ROOT / "backend" / "core" / "input" / "frida" / "scripts",
        "backend/core/input/frida/scripts",
    )
    # Keep examples optional for first-run demos
    add(ROOT / "examples", "examples")
    return pairs


def build_exe(*, onefile: bool) -> None:
    ensure_pyinstaller()
    icon = ensure_app_icon(force=True)
    datas = collect_datas()
    if not any(d[1].startswith("frontend/dist") for d in datas):
        raise SystemExit("frontend/dist not found - run without --skip-frontend")

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
        f"--icon={icon}",
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
        exe_path = OUT_DIR / f"{target_name}.exe"
        print(f"\nOK: {exe_path}")
        finalize_windows_exe_icon(exe_path)
    else:
        exe_path = OUT_DIR / target_name / f"{target_name}.exe"
        print(f"\nOK: {exe_path}")
        print("  (onedir - keep the whole folder together)")
        finalize_windows_exe_icon(exe_path)


def _exe_has_icon_resource(exe_path: Path) -> bool:
    try:
        import pefile
    except ImportError:
        try:
            run([sys.executable, "-m", "pip", "install", "pefile", "-q"])
            import pefile
        except Exception:
            return True  # skip verify
    try:
        pe = pefile.PE(str(exe_path))
        ok = False
        if hasattr(pe, "DIRECTORY_ENTRY_RESOURCE"):
            for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
                if entry.id == 14:  # RT_GROUP_ICON
                    ok = True
                    break
        pe.close()
        return ok
    except Exception as exc:
        print(f"! icon verify skipped: {exc}")
        return True


def finalize_windows_exe_icon(exe_path: Path) -> None:
    """Confirm icon is embedded and notify Windows Explorer (no extra exe copy)."""
    if not exe_path.is_file():
        return
    if not _exe_has_icon_resource(exe_path):
        print(f"! WARNING: {exe_path.name} has no embedded icon resource")
        return
    print(f"OK: {exe_path.name} contains embedded icon resources")

    try:
        import ctypes

        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNE_UPDATEITEM = 0x00002000
        SHCNF_IDLIST = 0x0000
        SHCNF_PATHW = 0x0005
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
        ctypes.windll.shell32.SHChangeNotify(
            SHCNE_UPDATEITEM, SHCNF_PATHW, str(exe_path), None
        )
    except Exception as exc:
        print(f"! SHChangeNotify failed: {exc}")


def read_channel_version() -> str | None:
    from backend.version_sync import read_channel_version as _read

    return _read(ROOT)


def inject_version(version: str) -> None:
    """Bake version into backend/version.py only (do not rewrite app_update history)."""
    from backend.version_sync import inject_version as _inject

    try:
        ver = _inject(version, root=ROOT)
    except ValueError:
        raise SystemExit("empty --version") from None
    except Exception as exc:
        raise SystemExit(str(exc)) from exc
    print(f"OK: injected version {ver} -> {ROOT / 'backend' / 'version.py'}")


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
    parser.add_argument(
        "--version",
        default=os.environ.get("NEXUZ_VERSION", "").strip() or None,
        help="Bake app version (default: app_update.json / NEXUZ_VERSION)",
    )
    args = parser.parse_args()

    if sys.platform != "win32":
        print("warning: packaging is intended for Windows (WebView2)")

    from backend.version_sync import sync_version_from_app_update

    version = args.version or read_channel_version()
    if args.version:
        inject_version(version)
    else:
        synced = sync_version_from_app_update(root=ROOT)
        if not synced:
            print("! no version from --version / NEXUZ_VERSION / app_update.json")

    if not args.skip_frontend:
        build_frontend()
    elif not DIST_UI.exists():
        raise SystemExit("frontend/dist missing - remove --skip-frontend")
    else:
        # Still refresh UI logo even when skipping full rebuild
        root_logo = ROOT / "logo.png"
        dist_logo = FRONTEND / "dist" / "logo.png"
        if root_logo.exists():
            shutil.copy2(root_logo, dist_logo)
            public_logo = FRONTEND / "public" / "logo.png"
            public_logo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root_logo, public_logo)

    build_exe(onefile=not bool(args.onedir))


if __name__ == "__main__":
    main()
