"""Coordinate click playback via Win32 mouse (multi-monitor safe)."""

from __future__ import annotations

from typing import Any

from backend.blocks._helpers import resolve_point
from backend.core.host_window import yield_host_mouse
from backend.core.input.provider_base import PlaybackProvider
from backend.core.input.types import ClickTarget
from backend.core.input.win32_mouse import click_at


class CoordPlaybackProvider(PlaybackProvider):
    mode = "coord"

    def execute(self, target: ClickTarget, context: dict[str, Any] | None = None) -> dict[str, Any]:
        params = target.to_params()
        # Playback-only flag (not part of ClickTarget) — see click multi-mode.
        if isinstance(context, dict) and "__activate_window" in context:
            params["activate_window"] = context["__activate_window"]
        x, y = resolve_point(params)
        button = target.button or "left"
        clicks = 2 if target.click_type == "double" else 1
        move_duration = float(target.move_duration or 0) / 1000.0
        try:
            # Yield hit-testing so topmost Nexuz chrome cannot eat the click.
            with yield_host_mouse():
                # Always move first, then settle: Unity/UI kits often miss a
                # teleport+immediate-click (no PointerEnter) on earlier multi points.
                # Use Win32 SetCursorPos — pyautogui.moveTo remaps secondary-monitor
                # virtual coords against primary size only (wrong x/y on monitor 2+).
                moved = click_at(
                    x,
                    y,
                    button=button if button in ("left", "right", "middle") else "left",
                    clicks=clicks,
                    move_duration=max(0.0, move_duration),
                    settle_s=0.05,
                    click_interval_s=0.05,
                )
        except Exception as exc:
            name = type(exc).__name__
            if "FailSafe" in name or "fail-safe" in str(exc).lower():
                raise RuntimeError(
                    "鼠标位于屏幕角落，触发了 PyAutoGUI 紧急停止。"
                    "请把鼠标移开角落后再试（调试时勿把指针甩到左上角）。"
                ) from exc
            raise
        out: dict[str, Any] = {
            "ok": True,
            "x": int(moved.get("x", x)),
            "y": int(moved.get("y", y)),
            "actual_x": moved.get("actual_x"),
            "actual_y": moved.get("actual_y"),
            "button": button,
        }
        try:
            from backend.core.window_coords import describe_screen_hit

            out.update(describe_screen_hit(int(out["x"]), int(out["y"])))
        except Exception:
            pass
        return out
