from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from backend.blocks import ai_object_cut


def _build_panel() -> np.ndarray:
    """240x240 BGRA 弹窗面板：

    - 主体棕色矩形 (rows 20..220, cols 20..200)
    - 红色圆形关闭按钮：圆心 (x=185, y=40) 半径 22，叠在面板右上角，
      与面板像素连通成单一连通域（纯几何方法无法分离）
    - 独立小杂质 (rows 5..10, cols 230..238)，供最大主体过滤
    """
    img = np.zeros((240, 240, 4), dtype=np.uint8)
    img[20:220, 20:200, 3] = 255
    img[20:220, 20:200, :3] = (60, 90, 150)  # BGR 棕色
    cv2.circle(img, (185, 40), 22, (40, 40, 220, 255), -1)  # BGR 红色按钮
    img[5:10, 230:238, 3] = 255
    img[5:10, 230:238, :3] = (200, 200, 200)
    return img


def _encode(path, img) -> Path:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    buf.tofile(str(path))
    return path


def _read(path) -> np.ndarray:
    data = cv2.imdecode(
        np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED
    )
    assert data is not None and data.ndim == 3 and data.shape[2] == 4
    return data


BASE_PARAMS = {
    "remove_desc": "右上角的红色圆形关闭按钮",
    "inpaint": "false",
    "padding": 0,
    "feather": 0,
    "timeout_s": 90,
    "name_prefix": "",
}


def _run(tmp_path, panel_path, monkeypatch, locate_bbox=(163, 18, 207, 62), **overrides):
    """mock 掉 AI 配置与视觉调用后执行 handler。

    locate_bbox 传 None 时模拟「AI 未找到目标」。
    """
    monkeypatch.setattr(
        ai_object_cut,
        "get_ai_config",
        lambda: SimpleNamespace(base_url="http://x/v1", api_key="k", model="m"),
    )

    def fake_locate(b64, scaled_wh, ai_cfg, remove_desc, timeout_s, image_sha=""):
        assert ai_cfg["model"] == "m"
        assert "关闭按钮" in remove_desc
        if locate_bbox is None:
            return json.dumps({"targets": []})
        return json.dumps(
            {"targets": [{"label": "关闭按钮", "bbox": list(locate_bbox)}]}
        )

    monkeypatch.setattr(ai_object_cut, "_ai_locate", fake_locate)

    params = {
        **BASE_PARAMS,
        "image_path": str(panel_path),
        "output_dir": str(tmp_path / "out"),
        **overrides,
    }
    return ai_object_cut.handler(params, context=None)


def test_cut_main_object_erase_button_without_inpaint(tmp_path, monkeypatch):
    """擦除关闭按钮（不修补）：按钮区透明成洞，面板主体完整保留，独立杂质被过滤。"""
    p = _encode(tmp_path / "panel.png", _build_panel())

    result = _run(tmp_path, p, monkeypatch)

    assert result["count"] == 1
    assert result["removed"] == 1
    out = _read(result["paths"][0])
    assert Path(result["paths"][0]).name == "panel_main.png"
    # 最大主体 = 面板 (rows 20..220, cols 20..200)，独立小杂质不混入
    assert out.shape[:2] == (200, 180)
    # 按钮圆心（原图 y=40,x=185 → 输出 20,165）被擦成透明洞
    assert out[20, 165, 3] == 0
    # 按钮下方面板本体（原图 y=70,x=185 → 输出 50,165）保持不透明
    assert out[50, 165, 3] == 255
    # 面板中心不受影响
    assert out[100, 80, 3] == 255
    assert tuple(out[100, 80, :3]) == (60, 90, 150)


def test_inpaint_keeps_open_notch_transparent(tmp_path, monkeypatch):
    """擦除后修补：与外部背景连通的缺口（角按钮超出面板轮廓的部分）保持透明，
    主图轮廓不被补出伪造凸块。"""
    p = _encode(tmp_path / "panel.png", _build_panel())

    result = _run(tmp_path, p, monkeypatch, inpaint="true")

    assert result["count"] == 1
    out = _read(result["paths"][0])
    # 角按钮缺口与外部连通 → 不补，保持透明缺口；面板主体完整
    assert out.shape[:2] == (200, 180)
    assert out[20, 165, 3] == 0
    assert out[100, 80, 3] == 255


def test_inpaint_fills_enclosed_watermark(tmp_path, monkeypatch):
    """面板内部完全被前景包围的杂质（水印）在修补模式下被补回不透明。"""
    img = _build_panel()
    img[60:90, 80:110, 3] = 255  # 内部白色水印方块（完全在面板内部）
    img[60:90, 80:110, :3] = (255, 255, 255)
    p = _encode(tmp_path / "marked.png", img)

    result = _run(
        tmp_path, p, monkeypatch,
        inpaint="true", locate_bbox=(80, 60, 110, 90),
        name_prefix="marked",
    )

    out = _read(result["paths"][0])
    assert Path(result["paths"][0]).name == "marked_main.png"
    # 水印中心（原图 y=75,x=95 → 输出 55,75）被修补为不透明
    assert out[55, 75, 3] == 255
    # 不修补时同位置是透明洞
    result2 = _run(
        tmp_path, p, monkeypatch,
        inpaint="false", locate_bbox=(80, 60, 110, 90),
        name_prefix="marked2",
    )
    out2 = _read(result2["paths"][0])
    assert out2[55, 75, 3] == 0


def test_no_targets_found_raises(tmp_path, monkeypatch):
    p = _encode(tmp_path / "panel.png", _build_panel())

    with pytest.raises(ValueError, match="未在图中定位到要去除的目标"):
        _run(tmp_path, p, monkeypatch, locate_bbox=None)


def test_empty_remove_desc_raises(tmp_path):
    p = _encode(tmp_path / "panel.png", _build_panel())
    with pytest.raises(ValueError, match="remove_desc"):
        ai_object_cut.handler(
            {
                "image_path": str(p),
                "output_dir": str(tmp_path / "out"),
                "remove_desc": "",
            },
            context=None,
        )


def test_ai_unconfigured_raises(tmp_path, monkeypatch):
    p = _encode(tmp_path / "panel.png", _build_panel())
    monkeypatch.setattr(
        ai_object_cut,
        "get_ai_config",
        lambda: SimpleNamespace(base_url="", api_key="", model=""),
    )
    with pytest.raises(ValueError, match="未配置聊天模型"):
        ai_object_cut.handler(
            {
                "image_path": str(p),
                "output_dir": str(tmp_path / "out"),
                "remove_desc": "关闭按钮",
            },
            context=None,
        )


def test_no_alpha_raises_with_hint(tmp_path):
    bgr = np.full((40, 40, 3), 100, dtype=np.uint8)
    p = _encode(tmp_path / "flat.png", bgr)
    with pytest.raises(ValueError, match="浅色底自动抠除"):
        ai_object_cut.handler(
            {
                "image_path": str(p),
                "output_dir": str(tmp_path / "out"),
                "remove_desc": "按钮",
            },
            context=None,
        )


def test_batch_mode_aggregates_errors(tmp_path, monkeypatch):
    """批量：正常图出主图，单张 AI 定位失败进 errors 不中断。"""
    folder = tmp_path / "imgs"
    folder.mkdir()
    _encode(folder / "a.png", _build_panel())
    _encode(folder / "b.png", _build_panel())

    monkeypatch.setattr(
        ai_object_cut,
        "get_ai_config",
        lambda: SimpleNamespace(base_url="http://x/v1", api_key="k", model="m"),
    )

    def fake_locate(b64, scaled_wh, ai_cfg, remove_desc, timeout_s, image_sha=""):
        raise ValueError("HTTP 401 无效密钥")

    monkeypatch.setattr(ai_object_cut, "_ai_locate", fake_locate)
    result = ai_object_cut.handler(
        {
            "image_path": f"{folder / 'a.png'}\n{folder / 'b.png'}",
            "output_dir": str(tmp_path / "out"),
            "remove_desc": "右上角的红色圆形关闭按钮",
            "inpaint": "false",
        },
        context=None,
    )

    assert result["sheets"] == 2
    assert result["count"] == 0
    assert len(result["errors"]) == 2
    assert any("401" in e["error"] for e in result["errors"])


def test_batch_mixed_success_and_failure(tmp_path, monkeypatch):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _encode(folder / "a.png", _build_panel())
    _encode(folder / "b.png", _build_panel())

    monkeypatch.setattr(
        ai_object_cut,
        "get_ai_config",
        lambda: SimpleNamespace(base_url="http://x/v1", api_key="k", model="m"),
    )

    def fake_locate(b64, scaled_wh, ai_cfg, remove_desc, timeout_s, image_sha=""):
        # 无法区分来源，用可变状态切换：第一张成功，第二张失败
        if not hasattr(fake_locate, "called"):
            fake_locate.called = True
            return json.dumps(
                {"targets": [{"bbox": [163, 18, 207, 62]}]}
            )
        raise ValueError("超时")

    monkeypatch.setattr(ai_object_cut, "_ai_locate", fake_locate)
    result = ai_object_cut.handler(
        {
            "image_path": f"{folder / 'a.png'}\n{folder / 'b.png'}",
            "output_dir": str(tmp_path / "out"),
            "remove_desc": "右上角的红色圆形关闭按钮",
            "inpaint": "false",
        },
        context=None,
    )

    assert result["count"] == 1
    assert result["removed"] == 1
    assert len(result["errors"]) == 1
    assert len(result["paths"]) == 1


def test_parse_targets_variants():
    # 围栏 JSON + 前后杂质文本
    fenced = '好的，结果如下：\n```json\n{"targets": [{"label": "按钮", "bbox": [10.0, 20, 30.5, 40]}]}\n```\n以上'
    assert ai_object_cut._parse_targets(fenced) == [(10, 20, 30, 40)]
    # x2<x1 自动交换；无效项跳过
    swapped = '{"targets": [{"bbox": [50, 10, 20, 40]}, {"bbox": [1, 2]}, "junk"]}'
    assert ai_object_cut._parse_targets(swapped) == [(20, 10, 50, 40)]
    # 空 targets
    assert ai_object_cut._parse_targets('{"targets": []}') == []
    # 非 JSON / 缺 targets
    with pytest.raises(ValueError, match="JSON"):
        ai_object_cut._parse_targets("抱歉我找不到")
    with pytest.raises(ValueError, match="targets"):
        ai_object_cut._parse_targets('{"boxes": []}')


def test_schema_registered():
    from backend.core.registry import register_block

    register_block(ai_object_cut.SCHEMA, ai_object_cut.handler)
