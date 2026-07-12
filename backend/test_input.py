"""Tests for click capture resolve + provider registry + session contracts."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.input.frida.stable_id import stable_id_key, validate_stable_id
from backend.core.input.provider_registry import (
    get_provider_registry,
    reset_provider_registry_for_tests,
)
from backend.core.input.resolve import (
    effective_capture_mode,
    normalize_click_params,
    recorded_click_to_node_params,
)
from backend.core.input.types import ERROR_INVALID_MODE


def test_normalize_legacy_coord():
    t = normalize_click_params({"x": 10, "y": 20, "button": "right"})
    assert t.capture_mode == "coord"
    assert t.button == "right"
    assert t.coord is not None
    assert t.coord.x == 10 and t.coord.y == 20
    params = t.to_params()
    assert params["x"] == 10
    assert params["capture_mode"] == "coord"
    assert params["button"] == "right"


def test_normalize_frida_nested():
    t = normalize_click_params(
        {
            "capture_mode": "frida_ui",
            "button": "left",
            "frida_ui": {
                "hierarchy_path": "Canvas/Ok",
                "component_type": "UnityEngine.UI.Button",
                "sibling_index": 1,
                "display_name": "Ok",
            },
        }
    )
    assert t.capture_mode == "frida_ui"
    assert t.frida_ui is not None
    assert t.frida_ui.hierarchy_path == "Canvas/Ok"
    assert t.frida_ui.sibling_index == 1


def test_effective_mode_priority():
    assert effective_capture_mode({"capture_mode": "frida_ui"}, "coord") == "frida_ui"
    assert effective_capture_mode({}, "frida_ui") == "frida_ui"
    assert effective_capture_mode({}, None) == "coord"
    assert effective_capture_mode({"capture_mode": ""}, "frida_ui") == "frida_ui"


def test_recorded_click_params():
    p = recorded_click_to_node_params(mode="coord", button="middle", x=1, y=2)
    assert p["capture_mode"] == "coord"
    assert p["button"] == "middle"
    assert p["x"] == 1
    f = recorded_click_to_node_params(
        mode="frida_ui",
        button="right",
        frida_ui={"hierarchy_path": "A/B", "component_type": "UnityEngine.UI.Toggle"},
    )
    assert f["capture_mode"] == "frida_ui"
    assert f["frida_ui"]["hierarchy_path"] == "A/B"
    assert f["button"] == "right"


def test_stable_id():
    ok, _ = validate_stable_id({"hierarchy_path": "Canvas/Btn"})
    assert ok
    bad, msg = validate_stable_id({"hierarchy_path": ""})
    assert not bad and msg
    key = stable_id_key(
        {"hierarchy_path": "A/B", "component_type": "Button", "sibling_index": 2}
    )
    assert key == "A/B|Button|2"


def test_provider_registry_lists_modes():
    reset_provider_registry_for_tests()
    reg = get_provider_registry()
    modes = {p["mode"] for p in reg.list_providers()}
    assert "coord" in modes
    assert "frida_ui" in modes
    coord = reg.require_capture("coord")
    assert not isinstance(coord, dict)
    bad = reg.require_capture("nope")
    assert isinstance(bad, dict)
    assert bad.get("error_code") == ERROR_INVALID_MODE


def test_frida_capture_unavailable_without_attach():
    reset_provider_registry_for_tests()
    from backend.core.input.frida.session_manager import reset_frida_session_manager_for_tests

    reset_frida_session_manager_for_tests()
    reg = get_provider_registry()
    err = reg.require_capture("frida_ui")
    assert isinstance(err, dict)
    assert err.get("ok") is False


def test_frida_session_status_detached():
    from backend.core.input.frida.session_manager import (
        get_frida_session_manager,
        reset_frida_session_manager_for_tests,
    )

    reset_frida_session_manager_for_tests()
    st = get_frida_session_manager().status()
    assert st["attached"] is False


def test_click_handler_coord(monkeypatch_unavailable=None):
    """Coord playback uses pyautogui — mock it."""
    import backend.core.input.providers.coord_playback as cp

    calls = []

    class FakePy:
        @staticmethod
        def moveTo(*a, **k):
            calls.append(("move", a, k))

        @staticmethod
        def click(*a, **k):
            calls.append(("click", a, k))

    import backend.blocks.click as click_mod

    # Patch via module used by CoordPlaybackProvider
    import backend.core.input.providers.coord_playback as playback_mod

    original = playback_mod.pyautogui
    playback_mod.pyautogui = FakePy  # type: ignore
    try:
        # Also patch resolve_point to avoid screen bounds
        import backend.blocks._helpers as helpers

        orig_resolve = helpers.resolve_point
        helpers.resolve_point = lambda params, x_key="x", y_key="y": (11, 22)  # type: ignore
        try:
            out = click_mod.handler(
                {"x": 11, "y": 22, "button": "right", "capture_mode": "coord"},
                {},
            )
            assert out.get("ok") is True
            assert any(c[0] == "click" for c in calls)
            assert calls[-1][2].get("button") == "right"
        finally:
            helpers.resolve_point = orig_resolve
    finally:
        playback_mod.pyautogui = original


def test_script_loader_exists():
    from backend.core.input.frida.script_loader import load_unity_ui_click_script, script_dir

    assert (script_dir() / "unity_ui_click.js").exists()
    src = load_unity_ui_click_script()
    assert "rpc.exports" in src
    assert "attachhooks" in src.lower() or "attachHooks" in src


if __name__ == "__main__":
    test_normalize_legacy_coord()
    test_normalize_frida_nested()
    test_effective_mode_priority()
    test_recorded_click_params()
    test_stable_id()
    test_provider_registry_lists_modes()
    test_frida_capture_unavailable_without_attach()
    test_frida_session_status_detached()
    test_click_handler_coord()
    test_script_loader_exists()
    # keep original expression tests runnable too
    from backend.test_unit import test_expressions, test_variables

    test_variables()
    test_expressions()
    print("INPUT + UNIT OK")
