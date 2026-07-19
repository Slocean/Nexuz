"""Always-on-top mini monitor while a flow runs with the main window hidden."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

_overlay_thread: threading.Thread | None = None
_close_fn: Callable[[], None] | None = None

_REFRESH_MS = 1500
_POLL_MS = 200


def show_run_overlay(
    on_stop: Callable[[], None],
    on_pause: Callable[[], None],
    *,
    flow_name: str = "",
    get_status: Callable[[], dict[str, Any]] | None = None,
) -> None:
    """Top-right panel: status + light resources + pause / stop."""
    hide_run_overlay()
    from backend.core.hotkey_prefs import get_pause_run_label, get_stop_run_label

    pause_label = get_pause_run_label()
    stop_label = get_stop_run_label()
    flow_title = (flow_name or "未命名流程").strip() or "未命名流程"

    def _run() -> None:
        global _close_fn
        try:
            import tkinter as tk
        except Exception:
            return

        root = tk.Tk()
        root.title("Nexuz 运行监控")
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        try:
            root.attributes("-toolwindow", True)
        except Exception:
            pass
        root.resizable(False, False)
        root.configure(bg="#121623")

        w, h = 300, 210
        sw = root.winfo_screenwidth()
        x = max(12, sw - w - 24)
        y = 24
        root.geometry(f"{w}x{h}+{x}+{y}")

        frame = tk.Frame(root, bg="#121623", padx=14, pady=12)
        frame.pack(fill="both", expand=True)

        title_lbl = tk.Label(
            frame,
            text="运行中",
            fg="#34D399",
            bg="#121623",
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        )
        title_lbl.pack(fill="x")

        flow_lbl = tk.Label(
            frame,
            text=_truncate(flow_title, 28),
            fg="#F5F7FB",
            bg="#121623",
            font=("Segoe UI", 9),
            anchor="w",
        )
        flow_lbl.pack(fill="x", pady=(4, 0))

        node_lbl = tk.Label(
            frame,
            text="节点 —",
            fg="#94A3B8",
            bg="#121623",
            font=("Segoe UI", 9),
            anchor="w",
        )
        node_lbl.pack(fill="x", pady=(2, 0))

        stats_lbl = tk.Label(
            frame,
            text="CPU — · 内存 —",
            fg="#94A3B8",
            bg="#121623",
            font=("Segoe UI", 9),
            anchor="w",
        )
        stats_lbl.pack(fill="x", pady=(2, 0))

        tk.Label(
            frame,
            text=f"暂停  {pause_label}    结束  {stop_label}",
            fg="#64748B",
            bg="#121623",
            font=("Segoe UI", 8),
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(8, 10))

        row = tk.Frame(frame, bg="#121623")
        row.pack(fill="x")

        # closed: request from any thread; only the Tk thread destroys widgets.
        state = {
            "closed": False,
            "stop_requested": False,
            "poll_id": None,
            "next_stats_at": 0.0,
        }
        tk_thread = threading.current_thread()

        def _cancel_poll() -> None:
            aid = state.get("poll_id")
            if aid is None:
                return
            try:
                root.after_cancel(aid)
            except Exception:
                pass
            state["poll_id"] = None

        def _destroy_on_tk() -> None:
            """Must run on the Tk thread only."""
            global _close_fn
            if _close_fn is close:
                _close_fn = None
            _cancel_poll()
            try:
                root.quit()
            except Exception:
                pass
            try:
                root.destroy()
            except Exception:
                pass

        def close() -> None:
            """Thread-safe: any thread may request close; Tk thread performs destroy."""
            global _close_fn
            state["closed"] = True
            if _close_fn is close:
                _close_fn = None
            if threading.current_thread() is tk_thread:
                _destroy_on_tk()

        def do_pause() -> None:
            try:
                on_pause()
            except Exception:
                pass
            try:
                _apply_status()
            except Exception:
                pass

        def do_stop() -> None:
            if state["stop_requested"]:
                return
            state["stop_requested"] = True
            state["closed"] = True
            try:
                on_stop()
            except Exception:
                pass
            # Destroy only on this (Tk) thread — never rely on hide_run_overlay's
            # cross-thread close after flow_finished.
            _destroy_on_tk()

        def _apply_status() -> None:
            status: dict[str, Any] = {}
            if get_status is not None:
                try:
                    status = get_status() or {}
                except Exception:
                    status = {}

            paused = bool(status.get("paused"))
            if paused:
                title_lbl.configure(text="已暂停", fg="#F59E0B")
            else:
                title_lbl.configure(text="运行中", fg="#34D399")

            name = str(status.get("flow_name") or flow_title).strip() or flow_title
            flow_lbl.configure(text=_truncate(name, 28))

            node_name = str(status.get("node_name") or "").strip()
            node_id = str(status.get("node_id") or "").strip()
            if node_name and node_id:
                node_lbl.configure(text=_truncate(f"节点 {node_name} ({node_id})", 36))
            elif node_name:
                node_lbl.configure(text=_truncate(f"节点 {node_name}", 36))
            elif node_id:
                node_lbl.configure(text=_truncate(f"节点 {node_id}", 36))
            else:
                node_lbl.configure(text="节点 —")

            cpu = status.get("cpu")
            rss_mb = status.get("rss_mb")
            try:
                cpu_s = f"{float(cpu):.1f}%" if cpu is not None else "—"
            except (TypeError, ValueError):
                cpu_s = "—"
            try:
                mem_s = f"{float(rss_mb):.0f} MB" if rss_mb is not None else "—"
            except (TypeError, ValueError):
                mem_s = "—"
            stats_lbl.configure(text=f"CPU {cpu_s} · 内存 {mem_s}")

        def poll() -> None:
            if state["closed"]:
                _destroy_on_tk()
                return
            try:
                if not root.winfo_exists():
                    return
            except Exception:
                return

            now = time.monotonic()
            if now >= float(state["next_stats_at"] or 0):
                state["next_stats_at"] = now + (_REFRESH_MS / 1000.0)
                try:
                    _apply_status()
                except Exception:
                    pass

            try:
                state["poll_id"] = root.after(_POLL_MS, poll)
            except Exception:
                state["poll_id"] = None

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
        try:
            _apply_status()
        except Exception:
            pass
        try:
            poll()
            root.mainloop()
        except Exception:
            pass
        finally:
            state["closed"] = True
            if _close_fn is close:
                _close_fn = None
            _cancel_poll()
            try:
                if root.winfo_exists():
                    root.destroy()
            except Exception:
                pass

    global _overlay_thread
    t = threading.Thread(target=_run, name="nexuz-run-overlay", daemon=True)
    _overlay_thread = t
    t.start()


def hide_run_overlay() -> None:
    """Request close. Safe from any thread — does not call Tk APIs directly."""
    global _close_fn, _overlay_thread
    fn = _close_fn
    _close_fn = None
    if fn:
        try:
            fn()
        except Exception:
            pass
    _overlay_thread = None


def _truncate(text: str, max_len: int) -> str:
    s = str(text or "")
    if len(s) <= max_len:
        return s
    if max_len <= 1:
        return s[:max_len]
    return s[: max_len - 1] + "…"
