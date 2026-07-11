"""Nexuz desktop entry — pywebview + React UI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_dpi_awareness()

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


def main() -> None:
    api = Api()
    url = resolve_ui_url()
    # Frameless: no OS title bar; app Toolbar provides drag + min/max/close
    window_kwargs = dict(
        title="Nexuz",
        url=url,
        js_api=api,
        width=1400,
        height=900,
        min_size=(1024, 700),
        frameless=True,
        easy_drag=False,
        background_color="#0A0D14",
    )
    # shadow is supported on recent pywebview (Windows); ignore if older
    try:
        window = webview.create_window(**window_kwargs, shadow=True)
    except TypeError:
        window = webview.create_window(**window_kwargs)
    api.set_window(window)
    webview.start(debug="--dev" in sys.argv)


if __name__ == "__main__":
    main()
