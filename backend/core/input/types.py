"""Click capture/playback platform types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CaptureMode = Literal["coord", "frida_ui"]
MouseButton = Literal["left", "right", "middle"]
ClickType = Literal["single", "double"]

ERROR_PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
ERROR_FRIDA_NOT_ATTACHED = "FRIDA_NOT_ATTACHED"
ERROR_STABLE_ID_RESOLVE_FAILED = "STABLE_ID_RESOLVE_FAILED"
ERROR_RECORDING_ACTIVE = "RECORDING_ACTIVE"
ERROR_NOT_RECORDING = "NOT_RECORDING"
ERROR_INVALID_MODE = "INVALID_MODE"
ERROR_CANCELLED = "CANCELLED"
ERROR_FRIDA_SCRIPT = "FRIDA_SCRIPT_ERROR"


@dataclass
class CoordTarget:
    x: int = 0
    y: int = 0
    point_norm: list[float] | None = None
    coord_space: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"x": int(self.x), "y": int(self.y)}
        if self.point_norm is not None:
            out["point_norm"] = list(self.point_norm)
        if self.coord_space is not None:
            out["coord_space"] = dict(self.coord_space)
        return out


@dataclass
class FridaUiTarget:
    hierarchy_path: str = ""
    component_type: str = "UnityEngine.UI.Button"
    sibling_index: int = 0
    display_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "hierarchy_path": self.hierarchy_path,
            "component_type": self.component_type,
            "sibling_index": int(self.sibling_index),
            "display_name": self.display_name or self.hierarchy_path.split("/")[-1],
        }

    @property
    def stable_id(self) -> dict[str, Any]:
        return {
            "hierarchy_path": self.hierarchy_path,
            "component_type": self.component_type,
            "sibling_index": int(self.sibling_index),
        }


@dataclass
class ClickTarget:
    capture_mode: CaptureMode = "coord"
    button: MouseButton = "left"
    click_type: ClickType = "single"
    move_duration: float = 0
    coord: CoordTarget | None = None
    frida_ui: FridaUiTarget | None = None

    def to_params(self) -> dict[str, Any]:
        """Flat + nested params for FlowModel click nodes (backward compatible)."""
        params: dict[str, Any] = {
            "capture_mode": self.capture_mode,
            "button": self.button,
            "click_type": self.click_type,
            "move_duration": self.move_duration,
        }
        if self.coord is not None:
            c = self.coord.to_dict()
            params["coord"] = c
            # Flat aliases for older UI / resolve_point
            params["x"] = c["x"]
            params["y"] = c["y"]
            if "point_norm" in c:
                params["point_norm"] = c["point_norm"]
            if "coord_space" in c:
                params["coord_space"] = c["coord_space"]
        if self.frida_ui is not None:
            params["frida_ui"] = self.frida_ui.to_dict()
        return params


@dataclass
class ProviderCapabilities:
    modes: list[str] = field(default_factory=lambda: ["sequence", "single"])
    buttons: list[str] = field(default_factory=lambda: ["left", "right", "middle"])
    requires_attach: bool = False
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "modes": list(self.modes),
            "buttons": list(self.buttons),
            "requires_attach": bool(self.requires_attach),
            "label": self.label,
        }


def api_error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    out = {"ok": False, "error_code": code, "error": message, "message": message}
    out.update(extra)
    return out


def api_ok(**extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": True}
    out.update(extra)
    return out
