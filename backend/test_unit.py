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


def test_click_outcome_summarizes_multi_points():
    from backend.core.runtime_payload import summarize_node_outcome

    text = summarize_node_outcome(
        "click",
        ok=True,
        result={
            "ok": True,
            "x": 50,
            "y": 60,
            "count": 3,
            "clicks": [
                {"index": 1, "x": 10, "y": 20},
                {"index": 2, "x": 30, "y": 40},
                {"index": 3, "x": 50, "y": 60},
            ],
        },
        elapsed_ms=120.0,
    )
    assert "多点点击 3 次" in text
    assert "(10, 20)" in text
    assert "(50, 60)" in text


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
    scaled, scale_x, scale_y = _prepare_ocr_image(tiny)
    assert scale_x > 1.0 and scale_y > 1.0
    assert scaled.size[0] > tiny.size[0]
    assert scaled.size[1] > tiny.size[1]
    big = Image.new("RGB", (200, 80), color=(255, 255, 255))
    same, scale2x, scale2y = _prepare_ocr_image(big)
    assert scale2x == 1.0 and scale2y == 1.0
    assert same.size == big.size

    # Large inputs are capped before RapidOCR and their coordinate scale is kept.
    huge = Image.new("RGB", (3200, 800), color=(255, 255, 255))
    reduced, scale3x, scale3y = _prepare_ocr_image(huge)
    assert scale3x == 0.5 and scale3y == 0.5
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


def test_ocr_window_client_output_and_click_bind():
    from backend.blocks._ocr_match import apply_output_coordinate_mode
    from backend.core.variable_resolver import attach_inferred_window_target

    fake_wt = {
        "process_name": "chrome.exe",
        "title": "Demo",
        "class_name": "Chrome_WidgetWin_1",
        "point_norm": [0.25, 0.5],
        "client_width": 800,
        "client_height": 600,
        "pid": 1,
    }
    stale_wt = {
        "process_name": "chrome.exe",
        "title": "Demo",
        "class_name": "Chrome_WidgetWin_1",
        "point_norm": [0.9, 0.9],
        "client_width": 800,
        "client_height": 600,
        "pid": 1,
    }

    with patch(
        "backend.core.window_coords.capture_window_target",
        return_value=dict(fake_wt),
    ):
        out = apply_output_coordinate_mode(
            {
                "found": True,
                "x": 120,
                "y": 240,
                "matches": [{"found": True, "x": 120, "y": 240, "query": "登录"}],
            },
            mode="window_client",
        )
    assert out["coordinate_mode"] == "window_client"
    assert out["x"] == 120 and out["y"] == 240
    assert out["window_target"]["point_norm"] == [0.25, 0.5]
    assert out["matches"][0]["window_target"]["process_name"] == "chrome.exe"

    raw = {
        "coordinate_mode": "window_client",
        "x": "{{ocr1.x}}",
        "y": "{{ocr1.y}}",
        # Stale take-point left on the click node — must not win over OCR bind.
        "window_target": dict(stale_wt),
        "coord": {"coordinate_mode": "window_client", "window_target": dict(stale_wt)},
    }
    ctx = {
        "ocr1.x": 120,
        "ocr1.y": 240,
        "ocr1.window_target": dict(fake_wt),
    }
    resolved = resolve_variables(raw, ctx)
    merged = attach_inferred_window_target(raw, resolved, ctx)
    assert merged["x"] == 120 and merged["y"] == 240
    # Must keep OCR-time point_norm (not retarget from abs x/y — that biases left if window moved).
    assert merged["window_target"]["point_norm"] == [0.25, 0.5]
    assert merged["coord"]["window_target"]["point_norm"] == [0.25, 0.5]
    assert merged["window_target"]["point_norm"] != stale_wt["point_norm"]


def test_ocr_substring_span_and_click_offset():
    from backend.blocks._ocr_match import (
        apply_click_offset,
        find_all_matching_boxes,
        find_all_match_spans,
        find_match_span,
        match_all_queries,
        match_text,
        order_match_hits,
        parse_match_options,
        pick_match_index,
    )

    line = "没有账号？注册"
    # exact = whole line only; contains crops to substring.
    assert not match_text(line, "注册", "exact")
    assert match_text(line, "注册", "contains")
    assert find_match_span(line, "注册", "contains") == (5, 7)

    # Normalize: fullwidth / OCR variants.
    opts = parse_match_options({"text_normalize": True})
    assert match_text("註冊", "注册", "contains", options=opts)
    assert match_text("LOGIN", "login", "exact", options=opts)

    # Fuzzy tolerates one edit (survives normalize).
    fuzzy_opts = parse_match_options({"text_normalize": True, "fuzzy_max_edits": 1})
    assert match_text("没有账号？注朋", "注册", "fuzzy", options=fuzzy_opts)

    box = {
        "text": line,
        "left": 100,
        "top": 200,
        "width": 140,
        "height": 20,
        "cx": 170,
        "cy": 210,
    }
    hits = find_all_matching_boxes([box], "注册", "contains")
    assert len(hits) == 1
    hit = hits[0]
    assert hit["text"] == "注册"
    assert hit["left"] == 200
    assert hit["width"] == 40
    assert hit["cx"] == 220
    assert hit["cy"] == 210

    assert not find_all_matching_boxes([box], "注册", "exact")
    full = find_all_matching_boxes([box], line, "exact")
    assert full and full[0]["cx"] == 170

    # Multiple occurrences in one line.
    multi = {
        "text": "注册或注册",
        "left": 0,
        "top": 0,
        "width": 100,
        "height": 10,
        "cx": 50,
        "cy": 5,
    }
    spans = find_all_match_spans(multi["text"], "注册", "contains")
    assert len(spans) == 2
    multi_hits = find_all_matching_boxes([multi], "注册", "contains")
    assert len(multi_hits) == 2
    ordered = order_match_hits(multi_hits, order="right")
    assert pick_match_index(ordered, 1)["cx"] >= pick_match_index(ordered, -1)["cx"]
    selected = match_all_queries(
        [multi],
        ["注册"],
        "contains",
        options=parse_match_options({"match_index": 2, "match_order": "reading"}),
    )
    assert selected[0]["found"] and selected[0]["primary_index"] == 2
    assert selected[0]["count"] == 2

    # Mixed CJK/ASCII width: "AB注册" — Latin weight 1, CJK 2.
    mixed = {
        "text": "AB注册",
        "left": 0,
        "top": 0,
        "width": 60,  # weights 1+1+2+2 = 6 → unit 10
        "height": 10,
        "cx": 30,
        "cy": 5,
    }
    mhit = find_all_matching_boxes([mixed], "注册", "contains")[0]
    assert mhit["left"] == 20
    assert mhit["width"] == 40

    # Vertical box slices Y for partial hits on tall glyphs.
    vert_line = {
        "text": "点注册",
        "left": 10,
        "top": 0,
        "width": 12,
        "height": 60,
        "cx": 16,
        "cy": 30,
    }
    vhit = find_all_matching_boxes([vert_line], "注册", "contains")[0]
    assert vhit["top"] > 0
    assert vhit["height"] < 60

    shifted = apply_click_offset(
        {"found": True, "x": 220, "y": 210, "left": 200, "top": 200, "cx": 220, "cy": 210},
        offset_x=8,
        offset_y=-4,
    )
    assert shifted["x"] == 228 and shifted["y"] == 206
    assert shifted["left"] == 208 and shifted["top"] == 196


if __name__ == "__main__":
    test_variables()
    test_expressions()
    test_pre_step_delay_ms()
    test_node_pre_delay_ms()
    test_interpreter_node_delay()
    test_coordinate_modes()
    test_runtime_logs_are_scoped_per_flow()
    test_ocr_memory_helpers()
    test_ocr_window_client_output_and_click_bind()
    test_ocr_substring_span_and_click_offset()
    print("UNIT OK")
