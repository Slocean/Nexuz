"""Always-on-top floating 'Stop recording' control."""

from __future__ import annotations

import threading
from typing import Callable


_overlay_thread: threading.Thread | None = None
_close_fn: Callable[[], None] | None = None


def show_stop_overlay(on_stop: Callable[[], None]) -> None:
    """Show a small topmost button. Clicking it calls on_stop once."""
    hide_stop_overlay()

    def _run():
        global _close_fn
        try:
            import tkinter as tk
        except Exception:
            return

        root = tk.Tk()
        root.title("Nexuz 录制")
        root.attributes("-topmost", True)
        root.overrideredirect(True)
        root.configure(bg="#1A2235")

        # Top-right-ish of primary screen
        try:
            sw = root.winfo_screenwidth()
            x = max(20, sw - 280)
        except Exception:
            x = 40
        root.geometry(f"260x88+{x}+24")

        frame = tk.Frame(root, bg="#1A2235", padx=12, pady=10)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text="正在录制鼠标/键盘…",
            fg="#E8EEFF",
            bg="#1A2235",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")

        tk.Label(
            frame,
            text="停止：点下方按钮 或 Ctrl+Shift+F10",
            fg="#9AA6BF",
            bg="#1A2235",
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(2, 8))

        stopped = {"done": False}

        def do_stop():
            if stopped["done"]:
                return
            stopped["done"] = True
            try:
                on_stop()
            finally:
                try:
                    root.quit()
                except Exception:
                    pass

        btn = tk.Button(
            frame,
            text="停止录制",
            command=do_stop,
            bg="#FF5E57",
            fg="#FFFFFF",
            activebackground="#E04842",
            activeforeground="#FFFFFF",
            relief="flat",
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            padx=10,
            pady=4,
        )
        btn.pack(fill="x")

        def close():
            try:
                root.quit()
            except Exception:
                pass

        _close_fn = close
        root.mainloop()
        try:
            root.destroy()
        except Exception:
            pass
        _close_fn = None

    global _overlay_thread
    t = threading.Thread(target=_run, daemon=True)
    _overlay_thread = t
    t.start()


def hide_stop_overlay() -> None:
    global _close_fn, _overlay_thread
    fn = _close_fn
    _close_fn = None
    if fn:
        try:
            fn()
        except Exception:
            pass
    _overlay_thread = None
