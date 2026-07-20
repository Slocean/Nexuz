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


def test_multi_click_hits_each_point():
    """Multi mode must invoke playback once per point (not only the last)."""
    import backend.blocks.click as click_mod
    import backend.core.input.providers.coord_playback as playback_mod
    from backend.core import host_window

    seen = []
    moves = []
    yields = []
    resolve_flags = []

    class FakePy:
        @staticmethod
        def moveTo(x=None, y=None, duration=0, *a, **k):
            moves.append((int(x), int(y)))

        @staticmethod
        def click(x=None, y=None, button="left", clicks=1, interval=0.05):
            # Playback clicks at current cursor after moveTo (x/y may be omitted).
            if x is None and moves:
                x, y = moves[-1]
            seen.append((int(x or 0), int(y or 0), button, int(clicks)))

    def fake_resolve(params, x_key="x", y_key="y"):
        resolve_flags.append(params.get("activate_window", "unset"))
        return int(params.get(x_key) or 0), int(params.get(y_key) or 0)

    orig_py = playback_mod.pyautogui
    orig_resolve = playback_mod.resolve_point
    orig_sleep = playback_mod.time.sleep
    host_window.register_mouse_yield(
        lambda: yields.append("begin"),
        lambda: yields.append("end"),
    )
    playback_mod.pyautogui = FakePy  # type: ignore
    playback_mod.resolve_point = fake_resolve  # type: ignore
    playback_mod.time.sleep = lambda *_a, **_k: None  # type: ignore
    try:
        out = click_mod.handler(
            {
                "click_mode": "multi",
                "capture_mode": "coord",
                "coordinate_mode": "screen_abs",
                "button": "left",
                "interval_ms": 0,
                "points": [
                    {"x": 10, "y": 20, "delay_ms": 0},
                    {"x": 30, "y": 40, "delay_ms": 0},
                    {"x": 50, "y": 60, "delay_ms": 0},
                ],
            },
            {},
        )
        assert out.get("ok") is True
        assert out.get("count") == 3
        assert seen == [
            (10, 20, "left", 1),
            (30, 40, "left", 1),
            (50, 60, "left", 1),
        ]
        assert [c["x"] for c in out.get("clicks") or []] == [10, 30, 50]
        # Each physical click must yield the host window so overlays don't eat it.
        assert yields == ["begin", "end", "begin", "end", "begin", "end"]
    finally:
        playback_mod.pyautogui = orig_py
        playback_mod.resolve_point = orig_resolve
        playback_mod.time.sleep = orig_sleep
        host_window.register_mouse_yield(None, None)


def test_multi_click_activates_window_only_once():
    """window_client multi-click must not SetForegroundWindow before every point."""
    import backend.blocks.click as click_mod
    import backend.core.input.providers.coord_playback as playback_mod
    from backend.core import host_window

    activate_flags = []

    class FakePy:
        @staticmethod
        def moveTo(*a, **k):
            pass

        @staticmethod
        def click(*a, **k):
            pass

    def fake_resolve(params, x_key="x", y_key="y"):
        activate_flags.append(params.get("activate_window", "unset"))
        return (
            100 + len(activate_flags) * 10,
            200 + len(activate_flags) * 10,
        )

    orig_py = playback_mod.pyautogui
    orig_resolve = playback_mod.resolve_point
    orig_sleep = playback_mod.time.sleep
    host_window.register_mouse_yield(lambda: None, lambda: None)
    playback_mod.pyautogui = FakePy  # type: ignore
    playback_mod.resolve_point = fake_resolve  # type: ignore
    playback_mod.time.sleep = lambda *_a, **_k: None  # type: ignore
    try:
        wt = {
            "process_name": "Game.exe",
            "title": "Game",
            "point_norm": [0.5, 0.5],
            "client_width": 800,
            "client_height": 600,
        }
        out = click_mod.handler(
            {
                "click_mode": "multi",
                "capture_mode": "coord",
                "coordinate_mode": "window_client",
                "button": "left",
                "interval_ms": 0,
                "points": [
                    {"x": 1, "y": 1, "delay_ms": 0, "coordinate_mode": "window_client", "window_target": {**wt, "point_norm": [0.1, 0.1]}},
                    {"x": 2, "y": 2, "delay_ms": 0, "coordinate_mode": "window_client", "window_target": {**wt, "point_norm": [0.2, 0.2]}},
                    {"x": 3, "y": 3, "delay_ms": 0, "coordinate_mode": "window_client", "window_target": {**wt, "point_norm": [0.3, 0.3]}},
                ],
            },
            {},
        )
        assert out.get("count") == 3
        assert activate_flags == [True, False, False]
    finally:
        playback_mod.pyautogui = orig_py
        playback_mod.resolve_point = orig_resolve
        playback_mod.time.sleep = orig_sleep
        host_window.register_mouse_yield(None, None)


def test_yield_host_mouse_noop_without_registration():
    from backend.core.host_window import register_mouse_yield, yield_host_mouse

    register_mouse_yield(None, None)
    with yield_host_mouse():
        pass


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
    test_multi_click_hits_each_point()
    test_multi_click_activates_window_only_once()
    test_yield_host_mouse_noop_without_registration()
    # keep original expression tests runnable too
    from backend.test_unit import test_expressions, test_variables

    test_variables()
    test_expressions()
    print("INPUT + UNIT OK")
