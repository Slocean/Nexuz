"""Normalize click params and resolve effective capture mode."""

from __future__ import annotations

from typing import Any

from backend.core.input.types import (
    CaptureMode,
    ClickTarget,
    CoordTarget,
    FridaUiTarget,
    MouseButton,
)


VALID_MODES: set[str] = {"coord", "frida_ui"}
VALID_BUTTONS: set[str] = {"left", "right", "middle"}


def coerce_button(value: Any, default: MouseButton = "left") -> MouseButton:
    s = str(value or default).lower().strip()
    if s in VALID_BUTTONS:
        return s  # type: ignore[return-value]
    return default


def coerce_mode(value: Any, default: CaptureMode = "coord") -> CaptureMode:
    s = str(value or default).strip()
    if s in VALID_MODES:
        return s  # type: ignore[return-value]
    return default


def effective_capture_mode(
    node_params: dict[str, Any] | None,
    default_capture_mode: str | None = None,
) -> CaptureMode:
    """
    Priority:
      node.params.capture_mode
      ?? appSettings.defaultCaptureMode
      ?? "coord"
    """
    params = node_params or {}
    if params.get("capture_mode") is not None and str(params.get("capture_mode")).strip():
        return coerce_mode(params.get("capture_mode"))
    if default_capture_mode is not None and str(default_capture_mode).strip():
        return coerce_mode(default_capture_mode)
    return "coord"


def _as_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _coord_from_params(params: dict[str, Any]) -> CoordTarget:
    nested = params.get("coord")
    if isinstance(nested, dict):
        return CoordTarget(
            x=_as_int(nested.get("x", params.get("x", 0)), 0),
            y=_as_int(nested.get("y", params.get("y", 0)), 0),
            point_norm=nested.get("point_norm", params.get("point_norm")),
            coord_space=nested.get("coord_space", params.get("coord_space")),
        )
    return CoordTarget(
        x=_as_int(params.get("x", 0), 0),
        y=_as_int(params.get("y", 0), 0),
        point_norm=params.get("point_norm"),
        coord_space=params.get("coord_space"),
    )


def _frida_from_params(params: dict[str, Any]) -> FridaUiTarget | None:
    nested = params.get("frida_ui")
    if not isinstance(nested, dict):
        return None
    path = str(nested.get("hierarchy_path") or "").strip()
    if not path:
        return None
    return FridaUiTarget(
        hierarchy_path=path,
        component_type=str(nested.get("component_type") or "UnityEngine.UI.Button"),
        sibling_index=int(nested.get("sibling_index", 0) or 0),
        display_name=str(nested.get("display_name") or ""),
    )


def normalize_click_params(params: dict[str, Any] | None) -> ClickTarget:
    """
    Accept legacy flat {x,y,button} and nested ClickTarget shapes.
    Missing capture_mode + has x/y => coord.
    """
    params = dict(params or {})
    mode: CaptureMode
    if params.get("capture_mode") is not None and str(params.get("capture_mode")).strip():
        mode = coerce_mode(params.get("capture_mode"))
    elif isinstance(params.get("frida_ui"), dict) and params["frida_ui"].get("hierarchy_path"):
        mode = "frida_ui"
    else:
        mode = "coord"

    button = coerce_button(params.get("button"))
    click_type = str(params.get("click_type") or "single")
    if click_type not in ("single", "double"):
        click_type = "single"
    move_duration = float(params.get("move_duration", 0) or 0)

    coord = _coord_from_params(params) if mode == "coord" or "x" in params or "coord" in params else None
    frida_ui = _frida_from_params(params)

    if mode == "coord" and coord is None:
        coord = CoordTarget()
    if mode == "frida_ui" and frida_ui is None:
        frida_ui = FridaUiTarget()

    return ClickTarget(
        capture_mode=mode,
        button=button,
        click_type=click_type,  # type: ignore[arg-type]
        move_duration=move_duration,
        coord=coord,
        frida_ui=frida_ui,
    )


def recorded_click_to_node_params(
    *,
    mode: CaptureMode,
    button: str,
    x: int | None = None,
    y: int | None = None,
    point_norm: list[float] | None = None,
    coord_space: dict[str, Any] | None = None,
    frida_ui: dict[str, Any] | None = None,
    click_type: str = "single",
    move_duration: float = 0,
) -> dict[str, Any]:
    """Build FlowModel click params from a single recorded action."""
    if mode == "frida_ui":
        target = ClickTarget(
            capture_mode="frida_ui",
            button=coerce_button(button),
            click_type=click_type if click_type in ("single", "double") else "single",  # type: ignore[arg-type]
            move_duration=move_duration,
            frida_ui=FridaUiTarget(
                hierarchy_path=str((frida_ui or {}).get("hierarchy_path") or ""),
                component_type=str(
                    (frida_ui or {}).get("component_type") or "UnityEngine.UI.Button"
                ),
                sibling_index=int((frida_ui or {}).get("sibling_index", 0) or 0),
                display_name=str((frida_ui or {}).get("display_name") or ""),
            ),
        )
        return target.to_params()

    coord = CoordTarget(
        x=int(x or 0),
        y=int(y or 0),
        point_norm=point_norm,
        coord_space=coord_space,
    )
    target = ClickTarget(
        capture_mode="coord",
        button=coerce_button(button),
        click_type=click_type if click_type in ("single", "double") else "single",  # type: ignore[arg-type]
        move_duration=move_duration,
        coord=coord,
    )
    return target.to_params()
