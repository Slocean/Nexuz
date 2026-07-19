"""Quick tests for expression + variable resolver."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.blocks._helpers import pre_step_delay_ms, resolve_point
from backend.core.expression import evaluate_expression
from backend.core.interpreter import FlowInterpreter, node_pre_delay_ms
from backend.core.runtime_log import RuntimeLogSession
from backend.core.variable_resolver import resolve_variables


def test_variables():
    ctx = {"node_1.text": "登录成功", "$count": 3, "count": 3}
    params = {"msg": "{{node_1.text}}", "n": "$count", "mixed": "hi-{{node_1.text}}"}
    out = resolve_variables(params, ctx)
    assert out["msg"] == "登录成功"
    assert out["n"] == 3
    assert out["mixed"] == "hi-登录成功"


def test_expressions():
    ctx = {"node_1.text": "登录成功", "node_2.matched": True, "a": 5}
    assert evaluate_expression('{{node_1.text}} == "登录成功"', ctx) is True
    assert evaluate_expression('{{node_1.text}} contains "登录"', ctx) is True
    assert evaluate_expression("{{node_2.matched}}", ctx) is True
    assert evaluate_expression("{{a}} > 3", ctx) is True
    assert evaluate_expression('{{node_1.text}} != "x"', ctx) is True
    assert evaluate_expression('{{node_1.text}} == "x"', ctx) is False


def test_pre_step_delay_ms():
    # First step: empty → no wait; explicit delay honored (the old multi-click bug).
    assert pre_step_delay_ms(0, None, default_interval=200) == 0
    assert pre_step_delay_ms(0, "", default_interval=200) == 0
    assert pre_step_delay_ms(0, 1500, default_interval=200) == 1500
    assert pre_step_delay_ms(0, "3000", default_interval=200) == 3000
    assert pre_step_delay_ms(0, 0, default_interval=200) == 0
    # Later steps: empty falls back to global interval; explicit overrides.
    assert pre_step_delay_ms(1, None, default_interval=200) == 200
    assert pre_step_delay_ms(1, "", default_interval=200) == 200
    assert pre_step_delay_ms(1, 50, default_interval=200) == 50
    assert pre_step_delay_ms(2, 0, default_interval=200) == 0


def test_node_pre_delay_ms():
    assert node_pre_delay_ms(0, None, 500) == 0
    assert node_pre_delay_ms(0, 120, 500) == 120
    assert node_pre_delay_ms(1, None, 500) == 500
    assert node_pre_delay_ms(3, "", 250) == 250
    assert node_pre_delay_ms(2, 0, 500) == 0
    assert node_pre_delay_ms(2, -10, 500) == 0


def test_interpreter_node_delay():
    waits: list[float] = []

    def handler(_params, _context, **_kwargs):
        return {"ok": True}

    flow = {
        "entry": "a",
        "__global_node_interval_ms": 250,
        "nodes": {
            "a": {"type": "stub", "params": {"node_delay_ms": 100}, "next": "b"},
            "b": {"type": "stub", "params": {}, "next": None},
        },
    }
    with (
        patch("backend.core.interpreter.get_handler", return_value=handler),
        patch(
            "backend.blocks._helpers.interruptible_sleep",
            side_effect=lambda seconds, **_kwargs: waits.append(seconds),
        ),
    ):
        FlowInterpreter()._execute(flow)
    assert waits == [0.1, 0.25]


def test_coordinate_modes():
    with (
        patch("backend.blocks._helpers.virtual_screen_size", return_value=(-1920, 0, 3840, 1080)),
        patch(
            "backend.blocks._helpers.virtual_screen_rect",
            return_value=(-1920, 0, 1920, 1080),
        ),
    ):
        # Absolute coordinates are never silently rescaled by an old coord_space.
        assert resolve_point(
            {
                "x": 100,
                "y": 200,
                "coordinate_mode": "screen_abs",
                "coord_space": {"left": 0, "top": 0, "w": 1920, "h": 1080},
            }
        ) == (100, 200)
        assert resolve_point(
            {
                "x": 100,
                "y": 200,
                "coordinate_mode": "virtual_norm",
                "point_norm": [0.75, 0.5],
            }
        ) == (960, 540)


def test_runtime_logs_are_scoped_per_flow():
    with tempfile.TemporaryDirectory() as td:
        with patch("backend.core.runtime_log.get_data_dir", return_value=Path(td)):
            first = RuntimeLogSession({"flow_id": "flow-a", "name": "流程甲"})
            first.write("node_start", {"node_id": "a"})
            first.close({"ok": True})
            second = RuntimeLogSession({"flow_id": "flow-b", "name": "流程乙"})
            second.write("node_start", {"node_id": "b"})
            second.close({"ok": True})
            first_info = first.info()
            second_info = second.info()
            assert first_info["folder"] != second_info["folder"]
            assert "流程甲" in first.as_text()
            assert "流程乙" in second.as_text()
            assert '"node_id":"b"' not in first.as_text()


def test_ocr_memory_helpers():
    from PIL import Image

    from backend.blocks.ocr_recognize import (
        _dispose_ocr_engine,
        _infer_ocr,
        _is_ocr_memory_error,
        _prepare_ocr_image,
        reset_ocr_engine,
        run_ocr,
    )
    from backend.core.runtime_payload import summarize_node_outcome

    assert _is_ocr_memory_error(MemoryError("x"))
    assert _is_ocr_memory_error(
        RuntimeError(
            "[ONNXRuntimeError] : 6 : RUNTIME_EXCEPTION : bad allocation"
        )
    )
    assert not _is_ocr_memory_error(ValueError("请框选识别区域"))

    tiny = Image.new("RGB", (20, 10), color=(255, 255, 255))
    scaled, scale = _prepare_ocr_image(tiny)
    assert scale > 1.0
    assert scaled.size[0] > tiny.size[0]
    assert scaled.size[1] > tiny.size[1]
    big = Image.new("RGB", (200, 80), color=(255, 255, 255))
    same, scale2 = _prepare_ocr_image(big)
    assert scale2 == 1.0
    assert same.size == big.size

    # Large inputs are capped before RapidOCR and their coordinate scale is kept.
    huge = Image.new("RGB", (3200, 800), color=(255, 255, 255))
    reduced, scale3 = _prepare_ocr_image(huge)
    assert scale3 == 0.5
    assert reduced.size == (1600, 400)

    with tempfile.TemporaryDirectory() as td:
        image_path = Path(td) / "large.png"
        huge.save(image_path)
        fake_result = [
            [[[800, 200], [900, 200], [900, 250], [800, 250]], "目标", 0.9]
        ]
        with patch(
            "backend.blocks.ocr_recognize._infer_ocr",
            return_value=(fake_result, 0.01),
        ):
            mapped = run_ocr(
                {
                    "source_mode": "image",
                    "image_path": str(image_path),
                    "origin_x": 10,
                    "origin_y": 20,
                    "match_text": "目标",
                    "output_coordinate_mode": "screen_abs",
                }
            )
        assert mapped["left"] == 1610
        assert mapped["top"] == 420
        assert mapped["width"] == 200
        assert mapped["height"] == 100

    # Disposal follows RapidOCR 1.4.x's actual object layout.
    class Holder:
        pass

    engine = Holder()
    engine.text_det = Holder()
    engine.text_det.infer = Holder()
    engine.text_det.infer.session = object()
    engine.text_cls = Holder()
    engine.text_cls.infer = Holder()
    engine.text_cls.infer.session = object()
    engine.text_rec = Holder()
    engine.text_rec.session = object()
    det = engine.text_det
    cls = engine.text_cls
    rec = engine.text_rec
    _dispose_ocr_engine(engine)
    assert engine.text_det is None
    assert engine.text_cls is None
    assert engine.text_rec is None
    assert det.infer.session is None
    assert cls.infer.session is None
    assert rec.session is None

    calls = {"n": 0}

    class BoomThenOk:
        def __call__(self, _arr):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError(
                    "onnxruntime ... Status Message: bad allocation"
                )
            return [[[[0, 0], [10, 0], [10, 10], [0, 10]], "80", 0.9]], 1.0

    with (
        patch("backend.blocks.ocr_recognize._get_ocr", return_value=BoomThenOk()),
        patch("backend.blocks.ocr_recognize.reset_ocr_engine") as reset_mock,
    ):
        import numpy as np

        out, _elapsed = _infer_ocr(np.zeros((8, 8, 3), dtype=np.uint8))
        assert out and out[0][1] == "80"
        assert calls["n"] == 2
        assert reset_mock.called

    # Exhaust retries → surface platform engine error (not a "buy more RAM" message).
    class AlwaysBoom:
        def __call__(self, _arr):
            raise RuntimeError("onnxruntime Status Message: bad allocation")

    with (
        patch("backend.blocks.ocr_recognize._get_ocr", return_value=AlwaysBoom()),
        patch("backend.blocks.ocr_recognize.reset_ocr_engine"),
        patch("backend.blocks.ocr_recognize.time.sleep"),
    ):
        import numpy as np
        import pytest

        with pytest.raises(RuntimeError, match="OCR 引擎异常"):
            _infer_ocr(np.zeros((8, 8, 3), dtype=np.uint8))

    reset_ocr_engine()

    assert "识别为空" in summarize_node_outcome(
        "if_text_contains",
        ok=True,
        result={"matched": False, "recognized": False, "actual_text": ""},
    )
    assert "实际: 79" in summarize_node_outcome(
        "if_text_contains",
        ok=True,
        result={"matched": False, "recognized": True, "actual_text": "79"},
    )
    assert "成立" in summarize_node_outcome(
        "if_text_contains",
        ok=True,
        result={"matched": True, "recognized": True, "actual_text": "80"},
    )


if __name__ == "__main__":
    test_variables()
    test_expressions()
    test_pre_step_delay_ms()
    test_node_pre_delay_ms()
    test_interpreter_node_delay()
    test_coordinate_modes()
    test_runtime_logs_are_scoped_per_flow()
    test_ocr_memory_helpers()
    print("UNIT OK")
