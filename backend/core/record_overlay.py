"""Always-on-top stop-recording float — used only when main window is hidden."""
from __future__ import annotations

import threading
from typing import Callable

_overlay_thread: threading.Thread | None = None
_close_fn: Callable[[], None] | None = None


def show_stop_overlay(on_stop: Callable[[], None]) -> None:
    """Show a small topmost panel. Clicking stop calls on_stop once."""
    hide_stop_overlay()

    def _run() -> None:
        global _close_fn
        try:
            import tkinter as tk
        except Exception:
            return

        root = tk.Tk()
        root.title("Nexuz 录制")
        root.attributes("-topmost", True)
        try:
            root.attributes("-toolwindow", True)
        except Exception:
            pass
        root.resizable(False, False)
        root.configure(bg="#121623")

        # Place near top-right of primary screen
        w, h = 300, 148
        sw = root.winfo_screenwidth()
        x = max(12, sw - w - 24)
        y = 24
        root.geometry(f"{w}x{h}+{x}+{y}")

        frame = tk.Frame(root, bg="#121623", padx=14, pady=12)
        frame.pack(fill="both", expand=True)

        title = tk.Label(
            frame,
            text="正在录制",
            fg="#F5F7FB",
            bg="#121623",
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        )
        title.pack(fill="x")

        desc = tk.Label(
            frame,
            text="记录：点击 / 按键 / 延迟 / 滚轮。\n不含拖拽、悬停、打字。\n停止：按钮 或 Ctrl+X+F10",
            fg="#94A3B8",
            bg="#121623",
            font=("Segoe UI", 9),
            justify="left",
            anchor="w",
        )
        desc.pack(fill="x", pady=(6, 10))

        stopped = {"done": False}

        def do_stop() -> None:
            if stopped["done"]:
                return
            stopped["done"] = True
            try:
                on_stop()
            finally:
                close()

        def close() -> None:
            global _close_fn
            _close_fn = None
            try:
                root.destroy()
            except Exception:
                pass

        btn = tk.Button(
            frame,
            text="■  停止录制",
            command=do_stop,
            bg="#FF453A",
            fg="#FFFFFF",
            activebackground="#E03E34",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            height=2,
        )
        btn.pack(fill="x")

        root.protocol("WM_DELETE_WINDOW", do_stop)
        _close_fn = close
        root.mainloop()

    global _overlay_thread
    t = threading.Thread(target=_run, name="nexuz-record-overlay", daemon=True)
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
