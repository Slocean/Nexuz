"""Coordinate click playback via pyautogui."""

from __future__ import annotations

import time
from typing import Any

import pyautogui

from backend.blocks._helpers import resolve_point
from backend.core.host_window import yield_host_mouse
from backend.core.input.provider_base import PlaybackProvider
from backend.core.input.types import ClickTarget


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
                pyautogui.moveTo(x, y, duration=max(0.0, move_duration))
                time.sleep(0.05)
                # Click current position — avoid a second teleport inside click().
                pyautogui.click(button=button, clicks=clicks, interval=0.05)
        except Exception as exc:
            name = type(exc).__name__
            if "FailSafe" in name or "fail-safe" in str(exc).lower():
                raise RuntimeError(
                    "鼠标位于屏幕角落，触发了 PyAutoGUI 紧急停止。"
                    "请把鼠标移开角落后再试（调试时勿把指针甩到左上角）。"
                ) from exc
            raise
        out: dict[str, Any] = {"ok": True, "x": x, "y": y, "button": button}
        try:
            from backend.core.window_coords import describe_screen_hit

            out.update(describe_screen_hit(x, y))
        except Exception:
            pass
        return out
