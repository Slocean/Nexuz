"""Always-on-top tip while a flow runs with the main window hidden."""

from __future__ import annotations

import threading
from typing import Callable

from backend.core.run_hotkeys import PAUSE_LABEL, STOP_LABEL

_overlay_thread: threading.Thread | None = None
_close_fn: Callable[[], None] | None = None


def show_run_overlay(
    on_stop: Callable[[], None],
    on_pause: Callable[[], None],
) -> None:
    """Top-right panel: pause / stop + hotkey hints."""
    hide_run_overlay()

    def _run() -> None:
        global _close_fn
        try:
            import tkinter as tk
        except Exception:
            return

        root = tk.Tk()
        root.title("Nexuz 运行中")
        root.attributes("-topmost", True)
        try:
            root.attributes("-toolwindow", True)
        except Exception:
            pass
        root.resizable(False, False)
        root.configure(bg="#121623")

        w, h = 320, 168
        sw = root.winfo_screenwidth()
        x = max(12, sw - w - 24)
        y = 24
        root.geometry(f"{w}x{h}+{x}+{y}")

        frame = tk.Frame(root, bg="#121623", padx=14, pady=12)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text="流程运行中",
            fg="#F5F7FB",
            bg="#121623",
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).pack(fill="x")

        tk.Label(
            frame,
            text=f"暂停  {PAUSE_LABEL}\n结束  {STOP_LABEL}",
            fg="#94A3B8",
            bg="#121623",
            font=("Segoe UI", 9),
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(6, 10))

        row = tk.Frame(frame, bg="#121623")
        row.pack(fill="x")

        closed = {"done": False}

        def close() -> None:
            global _close_fn
            _close_fn = None
            try:
                root.destroy()
            except Exception:
                pass

        def do_pause() -> None:
            try:
                on_pause()
            except Exception:
                pass

        def do_stop() -> None:
            if closed["done"]:
                return
            closed["done"] = True
            try:
                on_stop()
            finally:
                close()

        tk.Button(
            row,
            text="暂停",
            command=do_pause,
            bg="#F59E0B",
            fg="#121623",
            activebackground="#D97706",
            activeforeground="#121623",
            relief="flat",
            bd=0,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            width=10,
            height=2,
        ).pack(side="left", expand=True, fill="x", padx=(0, 6))

        tk.Button(
            row,
            text="■  结束",
            command=do_stop,
            bg="#FF453A",
            fg="#FFFFFF",
            activebackground="#E03E34",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            width=10,
            height=2,
        ).pack(side="left", expand=True, fill="x")

        root.protocol("WM_DELETE_WINDOW", do_stop)
        _close_fn = close
        root.mainloop()

    global _overlay_thread
    t = threading.Thread(target=_run, name="nexuz-run-overlay", daemon=True)
    _overlay_thread = t
    t.start()


def hide_run_overlay() -> None:
    global _close_fn, _overlay_thread
    fn = _close_fn
    _close_fn = None
    if fn:
        try:
            fn()
        except Exception:
            pass
    _overlay_thread = None
