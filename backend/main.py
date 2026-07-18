"""Nexuz desktop entry — pywebview + React UI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Bootstrap project root onto sys.path before importing backend.*
_BOOT_ROOT = Path(__file__).resolve().parent.parent
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _BOOT_ROOT = Path(sys._MEIPASS)  # type: ignore[attr-defined]
if str(_BOOT_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOT_ROOT))

from backend.paths import project_root

ROOT = project_root()


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2. Must run before
            # importing webview/input libraries so all coordinates are physical pixels.
            ok = ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            if not ok:
                raise OSError("SetProcessDpiAwarenessContext failed")
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_dpi_awareness()

try:
    from backend.version_sync import sync_version_from_app_update

    sync_version_from_app_update(quiet=True)
except Exception:
    pass

import webview

from backend.api import Api


def resolve_ui_url() -> str:
    """Dev: Vite server; Prod: frontend/dist/index.html."""
    dev_url = os.environ.get("NEXUZ_DEV_URL", "http://127.0.0.1:5173")
    dist = ROOT / "frontend" / "dist" / "index.html"
    use_dist = os.environ.get("NEXUZ_USE_DIST", "").lower() in ("1", "true", "yes")
    if use_dist and dist.exists():
        return dist.as_uri()
    # Prefer dist if no explicit dev and dist exists and --dev not set
    if "--dev" in sys.argv:
        return dev_url
    if dist.exists() and "--dev" not in sys.argv:
        return dist.as_uri()
    return dev_url


def resolve_app_icon() -> str | None:
    """Path to .ico for Windows taskbar / window icon (pywebview.start)."""
    candidates = [
        ROOT / "logo.ico",
        ROOT / "logo.png",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def main() -> None:
    try:
        from backend.core.updater import cleanup_old_exe

        cleanup_old_exe()
    except Exception:
        pass

    api = Api()
    url = resolve_ui_url()
    icon = resolve_app_icon()
    # Frameless: no OS title bar; app Toolbar provides drag + min/max/close
    window_kwargs = dict(
        title="Nexuz",
        url=url,
        js_api=api,
        width=1400,
        height=900,
        min_size=(800, 560),
        frameless=True,
        easy_drag=False,
        background_color="#0A0D14",
    )
    # resizable / shadow: supported on recent pywebview; ignore if older
    for extra in ({"resizable": True, "shadow": True}, {"resizable": True}, {"shadow": True}, {}):
        try:
            window = webview.create_window(**window_kwargs, **extra)
            break
        except TypeError:
            continue
    else:
        window = webview.create_window(**window_kwargs)
    api.set_window(window)
    start_kwargs: dict = {"debug": "--dev" in sys.argv}
    if icon:
        start_kwargs["icon"] = icon
    try:
        webview.start(**start_kwargs)
    except TypeError:
        # Older pywebview without icon= support
        webview.start(debug="--dev" in sys.argv)


if __name__ == "__main__":
    main()
