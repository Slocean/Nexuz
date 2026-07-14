"""Coordinate click playback via pyautogui."""

from __future__ import annotations

from typing import Any

import pyautogui

from backend.blocks._helpers import resolve_point
from backend.core.input.provider_base import PlaybackProvider
from backend.core.input.types import ClickTarget


class CoordPlaybackProvider(PlaybackProvider):
    mode = "coord"

    def execute(self, target: ClickTarget, context: dict[str, Any] | None = None) -> dict[str, Any]:
        params = target.to_params()
        x, y = resolve_point(params)
        button = target.button or "left"
        clicks = 2 if target.click_type == "double" else 1
        move_duration = float(target.move_duration or 0) / 1000.0
        try:
            if move_duration > 0:
                pyautogui.moveTo(x, y, duration=move_duration)
            pyautogui.click(x=x, y=y, button=button, clicks=clicks, interval=0.05)
        except Exception as exc:
            name = type(exc).__name__
            if "FailSafe" in name or "fail-safe" in str(exc).lower():
                raise RuntimeError(
                    "鼠标位于屏幕角落，触发了 PyAutoGUI 紧急停止。"
                    "请把鼠标移开角落后再试（调试时勿把指针甩到左上角）。"
                ) from exc
            raise
        return {"ok": True, "x": x, "y": y, "button": button}
