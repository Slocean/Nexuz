"""Coordinate-based click capture (pynput)."""

from __future__ import annotations

import threading
from typing import Any

from pynput import mouse

from backend.core.input.provider_base import CaptureProvider
from backend.core.input.resolve import (
    apply_preferred_coordinate_mode,
    normalize_preferred_coordinate_mode,
    recorded_click_to_node_params,
)
from backend.core.input.types import (
    ERROR_CANCELLED,
    ProviderCapabilities,
    api_error,
    api_ok,
)


def _button_name(button) -> str:
    """Normalize pynput mouse button → left|right|middle."""
    try:
        name = str(getattr(button, "name", None) or button or "").lower()
        name = name.replace("button.", "").strip()
        if name == "right" or name.endswith(".right"):
            return "right"
        if name == "middle" or name.endswith(".middle"):
            return "middle"
        if name == "left" or name.endswith(".left"):
            return "left"
        if "right" in name:
            return "right"
        if "middle" in name:
            return "middle"
    except Exception:
        pass
    try:
        if button == mouse.Button.right:
            return "right"
        if button == mouse.Button.middle:
            return "middle"
    except Exception:
        pass
    return "left"


class CoordCaptureProvider(CaptureProvider):
    mode = "coord"
    capabilities = ProviderCapabilities(
        modes=["sequence", "single"],
        buttons=["left", "right", "middle"],
        requires_attach=False,
        label="坐标",
    )

    def __init__(self) -> None:
        # Reuse global Recorder for sequence (keyboard + mouse + stop hotkey)
        from backend.core.recorder import get_recorder

        self._recorder = get_recorder()
        self._preferred_coordinate_mode = "screen_abs"

    def is_available(self) -> tuple[bool, str | None]:
        return True, None

    def start_sequence(
        self,
        *,
        min_interval_ms: int = 50,
        coordinate_mode: str = "screen_abs",
    ) -> None:
        self._preferred_coordinate_mode = normalize_preferred_coordinate_mode(coordinate_mode)
        self._recorder.min_interval_ms = int(min_interval_ms)
        self._recorder.start()

    def stop_sequence(self) -> list[dict[str, Any]]:
        nodes = self._recorder.stop()
        preferred = self._preferred_coordinate_mode
        # Upgrade click params to ClickTarget shape
        upgraded: list[dict[str, Any]] = []
        for n in nodes:
            if n.get("type") == "click":
                p = n.get("params") or {}
                params = recorded_click_to_node_params(
                    mode="coord",
                    button=str(p.get("button") or "left"),
                    x=int(p.get("x", 0) or 0),
                    y=int(p.get("y", 0) or 0),
                    click_type=str(p.get("click_type") or "single"),
                    move_duration=float(p.get("move_duration", 0) or 0),
                )
                # Attach point_norm if we can pack now
                try:
                    from backend.blocks._helpers import pack_point

                    packed = pack_point(params["x"], params["y"])
                    params["point_norm"] = packed["point_norm"]
                    params["coord_space"] = packed["coord_space"]
                    if packed.get("window_target"):
                        params["window_target"] = packed["window_target"]
                    params["coord"] = {
                        "x": packed["x"],
                        "y": packed["y"],
                        "coordinate_mode": "screen_abs",
                        "point_norm": packed["point_norm"],
                        "coord_space": packed["coord_space"],
                    }
                    if packed.get("window_target"):
                        params["coord"]["window_target"] = packed["window_target"]
                except Exception:
                    pass
                apply_preferred_coordinate_mode(params, preferred)
                upgraded.append({**n, "params": params})
            else:
                upgraded.append(n)
        return upgraded

    def pick_single(
        self,
        *,
        timeout_s: float = 120,
        coordinate_mode: str = "screen_abs",
    ) -> dict[str, Any]:
        preferred = normalize_preferred_coordinate_mode(coordinate_mode)
        result: dict[str, Any] | None = None
        done = threading.Event()

        def on_click(x, y, button, pressed):
            nonlocal result
            if not pressed:
                return True
            btn = _button_name(button)
            try:
                from backend.blocks._helpers import pack_point, pixel_color

                packed = pack_point(int(x), int(y))
                try:
                    color = pixel_color(int(x), int(y))
                except Exception:
                    color = None
                params = recorded_click_to_node_params(
                    mode="coord",
                    button=btn,
                    x=packed["x"],
                    y=packed["y"],
                    point_norm=packed["point_norm"],
                    coord_space=packed["coord_space"],
                    window_target=packed.get("window_target"),
                )
                apply_preferred_coordinate_mode(params, preferred)
                result = api_ok(params=params, button=btn, color=color, **packed)
            except Exception as exc:
                result = api_error("PICK_FAILED", str(exc))
            done.set()
            return False

        listener = mouse.Listener(on_click=on_click)
        listener.start()
        finished = done.wait(timeout=float(timeout_s))
        try:
            listener.stop()
        except Exception:
            pass
        if not finished or result is None:
            return api_error(ERROR_CANCELLED, "取点已取消或超时", cancelled=True)
        return result
