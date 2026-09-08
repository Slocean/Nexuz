"""style_audit 样式审计：检查项口径、handler 路由与白名单接线。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from backend.blocks import _style_audit as core
from backend.blocks import style_audit as block

# ---------------------------------------------------------------- fixtures


def _solid(size=(200, 120), color=(245, 245, 245, 255)) -> Image.Image:
    return Image.new("RGBA", size, color)


def _rect(img: Image.Image, box, color, outline=None) -> None:
    left, top, right, bottom = box
    ImageDraw.Draw(img).rectangle([left, top, right - 1, bottom - 1], fill=color, outline=outline)


@pytest.fixture
def card_png(tmp_path: Path) -> Path:
    """浅灰卡片 + 深色标题条：透明贴图，内容区离画布四边各留 10px。"""
    img = Image.new("RGBA", (200, 120), (0, 0, 0, 0))
    _rect(img, (10, 10, 190, 110), (245, 245, 245, 255))
    _rect(img, (14, 14, 186, 30), (30, 30, 30, 255))
    path = tmp_path / "card.png"
    img.save(path)
    return path


def _box(text="开始", left=20, top=40, width=60, height=24, confidence=0.9) -> dict:
    return {"text": text, "confidence": confidence, "left": left, "top": top, "width": width, "height": height}


# ---------------------------------------------------------------- 检查项口径


def test_edge_out_of_canvas_detected():
    boxes = [_box(left=150, top=40, width=80, height=24)]  # 右缘超出 30px
    issues = core.check_edges(boxes, 200, 120, margin_px=2, origin=(0, 0))
    assert [i["type"] for i in issues] == ["text_out_of_canvas"]
    assert issues[0]["severity"] == "high"
    assert "右超出 30px" in issues[0]["detail"]


def test_edge_flush_is_info_not_error():
    boxes = [_box(left=0, top=40, width=60, height=24)]
    issues = core.check_edges(boxes, 200, 120, margin_px=2, origin=(0, 0))
    assert [i["type"] for i in issues] == ["text_edge_flush"]
    assert issues[0]["severity"] == "info"


def test_edge_respects_margin_tolerance():
    boxes = [_box(left=20, top=40, width=60, height=24)]
    assert core.check_edges(boxes, 200, 120, margin_px=2, origin=(0, 0)) == []


def test_edge_origin_offsets_output_coords():
    boxes = [_box(left=150, top=40, width=80, height=24)]
    issues = core.check_edges(boxes, 200, 120, margin_px=2, origin=(300, 500))
    assert issues[0]["left"] == 450 and issues[0]["top"] == 540
    assert issues[0]["width"] == 80


def test_overlap_detected_with_other_box():
    a = _box(text="确定", left=40, top=40, width=60, height=24)
    b = _box(text="取消", left=70, top=40, width=60, height=24)  # 相交 30x24 / min(60x24)=50%
    issues = core.check_overlap([a, b], origin=(0, 0))
    assert len(issues) == 1
    issue = issues[0]
    assert issue["type"] == "text_overlap" and issue["severity"] == "high"
    assert issue["other_box"]["text"] == "取消"
    assert "50%" in issue["detail"]


def test_overlap_ignores_distant_boxes():
    a = _box(text="确定", left=40, top=40, width=60, height=24)
    b = _box(text="取消", left=120, top=40, width=60, height=24)
    assert core.check_overlap([a, b], origin=(0, 0)) == []


def test_contrast_dark_on_white_passes():
    img = _solid((120, 60), (255, 255, 255, 255))
    _rect(img, (20, 20, 100, 40), (20, 20, 20, 255))  # 黑字白底
    import numpy as np

    arr = np.asarray(img)
    boxes = [_box(left=20, top=20, width=80, height=20)]
    ms = core.measure_contrast_all(arr, boxes)
    issues = core.check_contrast(ms, boxes, 4.5, (0, 0))
    assert issues == []
    # 取证字段：黑字白底 → 深色 fg / 浅色 bg，比值 > 4.5
    assert ms[0] is not None and ms[0]["ratio"] > 4.5
    assert ms[0]["fg"].upper() == "#141414" and ms[0]["bg"].upper() == "#FFFFFF"


def test_contrast_light_on_white_flagged():
    img = _solid((120, 60), (255, 255, 255, 255))
    _rect(img, (20, 20, 100, 40), (230, 230, 230, 255))  # 浅灰字白底
    import numpy as np

    arr = np.asarray(img)
    boxes = [_box(left=20, top=20, width=80, height=20)]
    ms = core.measure_contrast_all(arr, boxes)
    issues = core.check_contrast(ms, boxes, 4.5, (0, 0))
    assert len(issues) == 1
    assert issues[0]["type"] == "text_low_contrast"
    assert issues[0]["severity"] in ("medium", "high")
    ratio = float(issues[0]["detail"].split("对比度 ")[1].split(" <")[0])
    assert ratio < 1.6
    assert "fg #" in issues[0]["detail"] and "bg #" in issues[0]["detail"]


def test_contrast_ratio_known_values():
    assert core.contrast_ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0, abs=0.1)
    assert core.contrast_ratio((255, 255, 255), (255, 255, 255)) == pytest.approx(1.0)


def test_contrast_skips_tiny_boxes():
    img = _solid((60, 30), (255, 255, 255, 255))
    _rect(img, (20, 10, 24, 14), (200, 200, 200, 255))
    import numpy as np

    arr = np.asarray(img)
    boxes = [_box(left=20, top=10, width=4, height=4)]
    assert core.measure_contrast_all(arr, boxes) == [None]


def test_contrast_ring_excludes_foreign_elements():
    # v2 口径：外扩环内混入大片深色干扰块（席位圆点/阴影之类），
    # 背景只取环内与前景异侧（亮）像素，不被干扰块拉低
    import numpy as np

    img = _solid((220, 120), (255, 255, 255, 255))
    for x0 in (45, 65, 85):  # 三笔"笔画"，保证内框非单色
        _rect(img, (x0, 45, x0 + 10, 55), (20, 20, 20, 255))
    _rect(img, (122, 30, 180, 70), (10, 10, 10, 255))  # 环内深色干扰块（不碰内框）
    arr = np.asarray(img)
    boxes = [_box(left=40, top=40, width=80, height=20)]
    m = core.measure_contrast_all(arr, boxes)[0]
    assert m is not None
    assert m["ratio"] > 10
    assert m["bg"].upper() == "#FFFFFF"
    assert m["fg"].upper() == "#141414"


# ---------------------------------------------------------------- 装饰过滤


def test_text_likeness_filter_flags_decor_blank_and_tiny():
    img = _solid((200, 120), (245, 245, 245, 255))
    # 词框完全贴在实心装饰条上（COoO 场景：OCR 框紧贴金纹色带，框内无背景）
    _rect(img, (20, 20, 160, 36), (200, 160, 40, 255))
    boxes = [
        _box(text="COoO", left=20, top=20, width=140, height=16),
        _box(text="空", left=20, top=60, width=60, height=16),  # 纯背景 → 近空白
        _box(text="h", left=170, top=60, width=10, height=3),  # 字高过小
    ]
    marked = core.annotate_text_likeness(img, boxes, min_height=8)
    assert marked[0]["filtered"] and "过低" in marked[0]["filtered"]
    assert marked[1]["filtered"] and "过低" in marked[1]["filtered"]
    assert marked[2]["filtered"] and "字高" in marked[2]["filtered"]


def test_text_likeness_keeps_real_text():
    img = _solid((200, 120), (255, 255, 255, 255))
    for x0 in (30, 50, 70):
        _rect(img, (x0, 30, x0 + 12, 44), (20, 20, 20, 255))
    boxes = [_box(text="abc", left=25, top=25, width=60, height=24)]
    marked = core.annotate_text_likeness(img, boxes, min_height=8)
    assert marked[0]["filtered"] is None


def test_filtered_boxes_skip_checks_but_stay_in_texts():
    img = _solid((200, 120), (255, 255, 255, 255))
    for x0 in (30, 50, 70):
        _rect(img, (x0, 30, x0 + 12, 44), (20, 20, 20, 255))
    real = {"text": "a", "confidence": 0.9, "left": 25, "top": 25, "width": 60, "height": 24}
    decor = {"text": "b", "confidence": 0.9, "left": 25, "top": 25, "width": 60, "height": 24, "filtered": "实心/装饰纹理"}
    report = core.audit_image(img, text_boxes=[real, decor])
    assert report["filtered_count"] == 1
    assert all(i["text"] != "b" for i in report["issues"])
    texts = {t["text"]: t for t in report["texts"]}
    assert texts["b"]["filtered"] and texts["b"]["contrast"] is None
    assert texts["a"]["filtered"] is None and texts["a"]["contrast"] is not None


# ---------------------------------------------------------------- 区域裁剪


def test_handler_region_crops_and_offsets(tmp_path: Path):
    img = Image.new("RGBA", (200, 120), (255, 255, 255, 255))
    _rect(img, (40, 40, 100, 60), (20, 20, 20, 255))
    path = tmp_path / "full.png"
    img.save(path)
    # 词框是裁剪区局部坐标（配合 screenshot 整图 + region 复审的用法）
    result = block.handler(
        {
            "image_path": str(path),
            "text_source": "custom",
            "text_boxes": json.dumps([_box(text="标题", left=10, top=10, width=60, height=20)]),
            "region": [30, 30, 130, 90],
        },
        context={},
    )
    assert result["ok"] is True
    assert result["region"] == [30, 30, 130, 90]
    assert result["image"]["width"] == 100 and result["image"]["height"] == 60
    text = result["texts"][0]
    assert (text["left"], text["top"]) == (40, 40)  # 局部坐标 + region 原点
    assert text["contrast"] is not None and text["contrast"] > 10
    assert text["fg"].upper() == "#141414" and text["bg"].upper() == "#FFFFFF"


def test_handler_region_invalid_raises(tmp_path: Path, card_png: Path):
    with pytest.raises(ValueError, match="无效区域"):
        block.handler(
            {"image_path": str(card_png), "text_source": "none", "region": [50, 50, 50, 50]},
            context={},
        )


def test_handler_region_clamped_to_image(card_png: Path):
    result = block.handler(
        {"image_path": str(card_png), "text_source": "none", "region": [150, 100, 300, 200]},
        context={},
    )
    assert result["region"] == [150, 100, 200, 120]
    assert result["image"]["width"] == 50 and result["image"]["height"] == 20


# ---------------------------------------------------------------- 配色


def test_palette_dominant_colors_and_background():
    img = _solid((100, 80), (245, 245, 245, 255))
    _rect(img, (20, 20, 80, 60), (30, 30, 30, 255))
    pal = core.extract_palette(img, 4)
    hexes = [c["hex"] for c in pal["colors"]]
    assert "#F5F5F5" in [h.upper() for h in hexes]  # MEDIANCUT 对纯色输出精确值
    assert pal["background"] is not None and pal["background"].upper() == "#F0F0F0"
    assert pal["transparent_ratio"] == pytest.approx(0.0)
    assert pal["colors"][0]["ratio"] >= pal["colors"][-1]["ratio"]


def test_palette_transparent_canvas_background_none():
    img = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
    _rect(img, (30, 30, 70, 50), (200, 30, 30, 255))
    pal = core.extract_palette(img, 3)
    assert pal["background"] is None
    assert pal["transparent_ratio"] > 0.5


# ---------------------------------------------------------------- 主入口


def test_audit_image_full_report(tmp_path: Path):
    img = Image.new("RGBA", (200, 120), (0, 0, 0, 0))
    _rect(img, (10, 10, 190, 110), (245, 245, 245, 255))
    boxes = [
        _box(text="标题", left=150, top=40, width=80, height=24),  # 超出画布
        _box(text="贴边", left=0, top=60, width=60, height=24),  # 贴左缘
        _box(text="A", left=40, top=40, width=40, height=20),
        _box(text="B", left=60, top=40, width=40, height=20),  # 与 A 重叠
    ]
    report = core.audit_image(
        img,
        text_boxes=boxes,
        annotate_path=str(tmp_path / "a.png"),
        save_report_path=str(tmp_path / "r.json"),
    )
    types = {i["type"] for i in report["issues"]}
    assert {"text_out_of_canvas", "text_edge_flush", "text_overlap"} <= types
    assert report["issues"][0]["severity"] == "high"  # high 排最前
    assert report["issue_count"] == len(report["issues"])
    assert Path(report["annotated_path"]).is_file()
    loaded = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
    assert loaded["issue_count"] == report["issue_count"]


def test_audit_image_max_issues_truncates():
    img = _solid((300, 40))
    # left=i*15、width=30 → 相邻框各重叠一半，形成 5 对 overlap
    boxes = [_box(text=f"t{i}", left=i * 15, top=8, width=30, height=24) for i in range(6)]
    report = core.audit_image(img, text_boxes=boxes, checks=["occlusion"], max_issues=2)
    assert report["issue_count"] == 2
    assert report["issues_truncated"] is True


def test_audit_image_no_boxes_no_text_issues():
    img = _solid((100, 80))
    report = core.audit_image(img, text_boxes=[], checks=list(core.KNOWN_CHECKS))
    assert report["text_count"] == 0
    assert report["issues"] == []
    assert report["issue_count"] == 0


def test_parse_checks_rejects_unknown():
    with pytest.raises(ValueError, match="未知检查项"):
        core.parse_checks("edge_clipping,magic")


def test_parse_text_boxes_skips_invalid_entries():
    boxes = core.parse_text_boxes('[{"left":1,"top":2,"width":0,"height":5},{"left":1,"top":2,"width":10,"height":5,"text":"ok"}]')
    assert len(boxes) == 1 and boxes[0]["text"] == "ok"


# ---------------------------------------------------------------- handler


def test_handler_custom_boxes_end_to_end(tmp_path: Path, card_png: Path):
    result = block.handler(
        {
            "image_path": str(card_png),
            "text_source": "custom",
            "text_boxes": json.dumps([_box(text="标题", left=150, top=40, width=80, height=24)]),
            "origin_x": 100,
            "origin_y": 200,
            "annotate_path": str(tmp_path / "ann.png"),
        },
        context={},
    )
    assert result["ok"] is True
    assert result["text_count"] == 1
    assert result["issue_count"] >= 1
    # v2 口径：该框落在浅灰卡面上（内框单色、环同色 → 对比度 1.0），
    # 同时右缘超出画布——两类 issue 并存，按类型定位断言
    types = {i["type"] for i in result["issues"]}
    assert "text_out_of_canvas" in types
    issue = next(i for i in result["issues"] if i["type"] == "text_out_of_canvas")
    assert issue["left"] == 250 and issue["top"] == 240
    assert result["image"]["path"] == str(card_png)
    assert result["annotated_path"] and Path(result["annotated_path"]).is_file()
    # card 四周是 10px 透明边 → 边框环全透明，背景估计应为 None
    assert result["palette"]["background"] is None
    assert result["palette"]["transparent_ratio"] > 0


def test_handler_none_source_skips_text(tmp_path: Path, card_png: Path):
    result = block.handler({"image_path": str(card_png), "text_source": "none"}, context={})
    assert result["ok"] is True
    assert result["text_count"] == 0 and result["issue_count"] == 0
    assert result["issues"] == []
    assert result["palette"]  # 配色始终输出


def test_handler_custom_without_boxes_raises(tmp_path: Path, card_png: Path):
    with pytest.raises(ValueError, match="text_boxes"):
        block.handler({"image_path": str(card_png), "text_source": "custom", "text_boxes": "[]"}, context={})


def test_handler_missing_image_raises():
    with pytest.raises(ValueError, match="图片路径|不存在"):
        block.handler({"image_path": "", "text_source": "none"}, context={})


def test_handler_bad_checks_raises(card_png: Path):
    with pytest.raises(ValueError, match="未知检查项"):
        block.handler({"image_path": str(card_png), "text_source": "none", "checks": "nope"}, context={})


# ---------------------------------------------------------------- 接线


def test_block_registered_and_safe():
    from backend.core.ai.run_block import classify_run_block
    from backend.core.registry import BLOCK_REGISTRY, register_all_blocks

    if "style_audit" not in BLOCK_REGISTRY:
        register_all_blocks()
    assert "style_audit" in BLOCK_REGISTRY
    assert BLOCK_REGISTRY["style_audit"]["schema"]["category"] == "识别类"
    assert classify_run_block("style_audit") == "safe"


def test_handler_params_validate(card_png: Path):
    from backend.core.block_params_validate import validate_flow_params

    issues = validate_flow_params(
        {"nodes": {"n1": {"type": "style_audit", "params": {"image_path": str(card_png)}}}}
    )
    errors = [i for i in issues if i.get("level") == "error"]
    assert errors == []
