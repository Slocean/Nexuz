"""Fullscreen drag-to-select region picker (tkinter overlay)."""

from __future__ import annotations

import sys
import threading
from typing import Any


def _virtual_screen() -> tuple[int, int, int, int]:
    """Return (left, top, width, height) of the virtual desktop."""
    if sys.platform == "win32":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            left = int(user32.GetSystemMetrics(76))  # SM_XVIRTUALSCREEN
            top = int(user32.GetSystemMetrics(77))  # SM_YVIRTUALSCREEN
            width = int(user32.GetSystemMetrics(78))  # SM_CXVIRTUALSCREEN
            height = int(user32.GetSystemMetrics(79))  # SM_CYVIRTUALSCREEN
            if width > 0 and height > 0:
                return left, top, width, height
        except Exception:
            pass
    from backend.core.dpi import screen_size_logical

    w, h = screen_size_logical()
    return 0, 0, w, h


def pick_region_overlay(timeout: float = 120.0) -> dict[str, Any]:
    """
    Show a dim fullscreen overlay; drag to select a rectangle.
    Esc cancels. Release mouse to confirm (min size 4px).
    Coordinates are in the same space as mss / screen_size_logical.
    """
    result: dict[str, Any] = {"ok": False, "cancelled": True}
    done = threading.Event()
    error_box: list[str] = []

    def _run():
        try:
            import tkinter as tk
        except Exception as exc:
            error_box.append(str(exc))
            done.set()
            return

        left, top, width, height = _virtual_screen()
        start: list[int | None] = [None, None]
        rect_id = {"id": None}

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            root.attributes("-alpha", 0.35)
        except Exception:
            pass
        root.overrideredirect(True)
        root.geometry(f"{width}x{height}+{left}+{top}")
        root.configure(bg="#0B1020")
        root.deiconify()
        root.focus_force()

        canvas = tk.Canvas(
            root,
            width=width,
            height=height,
            bg="#0B1020",
            highlightthickness=0,
            cursor="crosshair",
        )
        canvas.pack(fill="both", expand=True)
        canvas.create_text(
            width // 2,
            36,
            text="拖拽框选区域 · 松开确认 · Esc 取消",
            fill="#E8EEFF",
            font=("Segoe UI", 14, "bold"),
        )

        def cancel(_event=None):
            result.clear()
            result.update({"ok": False, "cancelled": True})
            root.quit()

        def on_press(event):
            start[0], start[1] = int(event.x), int(event.y)
            if rect_id["id"] is not None:
                canvas.delete(rect_id["id"])
                rect_id["id"] = None

        def on_drag(event):
            if start[0] is None or start[1] is None:
                return
            x0, y0 = start[0], start[1]
            x1, y1 = int(event.x), int(event.y)
            if rect_id["id"] is not None:
                canvas.delete(rect_id["id"])
            rect_id["id"] = canvas.create_rectangle(
                x0,
                y0,
                x1,
                y1,
                outline="#4F8CFF",
                width=2,
                fill="#4F8CFF",
                stipple="gray50",
            )

        def on_release(event):
            if start[0] is None or start[1] is None:
                return
            x0, y0 = start[0], start[1]
            x1, y1 = int(event.x), int(event.y)
            ax1, ay1 = left + min(x0, x1), top + min(y0, y1)
            ax2, ay2 = left + max(x0, x1), top + max(y0, y1)
            if ax2 - ax1 < 4 or ay2 - ay1 < 4:
                return
            result.clear()
            result.update({"ok": True, "region": [ax1, ay1, ax2, ay2]})
            root.quit()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        root.bind("<Escape>", cancel)
        root.after(int(timeout * 1000), cancel)

        root.mainloop()
        try:
            root.destroy()
        except Exception:
            pass
        done.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    if not done.wait(timeout=timeout + 5):
        return {"ok": False, "cancelled": True, "error": "选区超时"}
    if error_box:
        return {"ok": False, "error": f"无法打开选区蒙版: {error_box[0]}"}
    return dict(result)


def pick_point_overlay(timeout: float = 120.0) -> dict[str, Any]:
    """Dim overlay; single left-click to pick a point. Esc cancels."""
    result: dict[str, Any] = {"ok": False, "cancelled": True}
    done = threading.Event()
    error_box: list[str] = []

    def _run():
        try:
            import tkinter as tk
        except Exception as exc:
            error_box.append(str(exc))
            done.set()
            return

        left, top, width, height = _virtual_screen()
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            root.attributes("-alpha", 0.28)
        except Exception:
            pass
        root.overrideredirect(True)
        root.geometry(f"{width}x{height}+{left}+{top}")
        root.configure(bg="#0B1020")
        root.deiconify()
        root.focus_force()

        canvas = tk.Canvas(
            root,
            width=width,
            height=height,
            bg="#0B1020",
            highlightthickness=0,
            cursor="crosshair",
        )
        canvas.pack(fill="both", expand=True)
        canvas.create_text(
            width // 2,
            36,
            text="单击拾取坐标 · Esc 取消",
            fill="#E8EEFF",
            font=("Segoe UI", 14, "bold"),
        )

        def cancel(_event=None):
            result.clear()
            result.update({"ok": False, "cancelled": True})
            root.quit()

        def on_click(event):
            x = left + int(event.x)
            y = top + int(event.y)
            color = None
            try:
                from backend.blocks._helpers import pixel_color

                color = pixel_color(x, y)
            except Exception:
                pass
            result.clear()
            result.update({"ok": True, "x": x, "y": y, "color": color})
            root.quit()

        canvas.bind("<ButtonPress-1>", on_click)
        root.bind("<Escape>", cancel)
        root.after(int(timeout * 1000), cancel)
        root.mainloop()
        try:
            root.destroy()
        except Exception:
            pass
        done.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    if not done.wait(timeout=timeout + 5):
        return {"ok": False, "cancelled": True, "error": "拾取超时"}
    if error_box:
        return {"ok": False, "error": f"无法打开拾取蒙版: {error_box[0]}"}
    return dict(result)
