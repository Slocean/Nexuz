from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.blocks import sprite_sheet_cut


def _build_sheet() -> np.ndarray:
    """2x2 精灵图（200x200，黑底 10）：

    - 格(0,0)：白色主体 + 内部黑色条纹（须保护）+ 贴身小光效（闭运算粘连保留）
      + 左上角小红标号（面积过滤丢弃）
    - 格(1,0)：贴左格线的灰色主体
    - 格(0,1)：纯背景空格
    - 格(1,1)：主体 + 远离的大部件（两部件均保留，包围盒合并）
    """
    img = np.full((200, 200, 3), 10, dtype=np.uint8)
    # 格(0,0)
    img[4:10, 4:8] = (40, 40, 220)  # 标号，面积 24 < 自动阈值 40
    img[30:85, 30:80] = 255  # 主体
    img[40:75, 50:56] = 5  # 内部黑色条纹
    img[55:61, 82:88] = 255  # 贴身光效，与主体间隔 2px
    # 格(1,0)：贴左格线
    img[130:180, 0:40] = 200
    # 格(1,1)：主体 + 远离的大部件
    img[120:150, 130:170] = 255
    img[160:190, 150:200] = 180
    return img


@pytest.fixture()
def sheet_path(tmp_path):
    ok, buf = cv2.imencode(".png", _build_sheet())
    assert ok
    p = tmp_path / "sheet.png"
    buf.tofile(str(p))
    return p


def _read(path) -> np.ndarray:
    data = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    assert data is not None and data.ndim == 3 and data.shape[2] == 4
    return data


BASE_PARAMS = {
    "grid_mode": "manual",
    "rows": 2,
    "cols": 2,
    "inset_margin": 2,
    "bg_color": "10,10,10",
    "tolerance": 15,
    "close_radius": 2,
    "min_area": 0,
    "padding": 0,
    "feather": 0,
}


def _run(tmp_path, sheet_path, **overrides):
    params = {
        **BASE_PARAMS,
        "image_path": str(sheet_path),
        "output_dir": str(tmp_path / "out"),
        **overrides,
    }
    return sprite_sheet_cut.handler(params, context=None)


def test_manual_grid_full_pipeline(tmp_path, sheet_path):
    result = _run(tmp_path, sheet_path)

    assert result["count"] == 3
    assert result["skipped"] == 1
    assert Path(result["output_dir"]).is_dir()

    by_name = {Path(p).name: p for p in result["paths"]}
    # 单元格命名含内缩后的原点：格(0,0)=r002c002，格(1,0)=r102c002，格(1,1)=r102c102
    assert set(by_name) == {"sheet_r002c002.png", "sheet_r102c002.png", "sheet_r102c102.png"}

    # 格(0,0)：包围盒 = 主体+光效的并集，未被标号扩大
    out = _read(by_name["sheet_r002c002.png"])
    assert out.shape[:2] == (55, 58)  # rows 30..85, cols 30..88
    # 内部黑色条纹被保护：不透明且保持原色
    assert out[15, 22, 3] == 255
    assert tuple(out[15, 22, :3]) == (5, 5, 5)
    # 贴身光效保留在主体右侧
    assert out[28, 55, 3] == 255

    # 格(1,0)：贴左格线，包围盒左缘裁到内缩边界
    out = _read(by_name["sheet_r102c002.png"])
    assert out.shape[:2] == (50, 38)  # rows 130..180, cols 2..40
    assert out[25, 0, 3] == 255

    # 格(1,1)：远离的大部件与主体合并为一个包围盒
    out = _read(by_name["sheet_r102c102.png"])
    assert out.shape[:2] == (70, 68)  # rows 120..190, cols 130..198(贴格线)
    assert out[10, 10, 3] == 255  # 主体
    assert out[45, 40, 3] == 255  # 远端部件


def test_auto_grid_detection(tmp_path, sheet_path):
    # 投影法：标号独占一个行带，其单元格内仅剩标号 → 被面积过滤后整格跳过
    result = _run(tmp_path, sheet_path, grid_mode="auto")

    assert result["count"] == 3
    assert result["skipped"] == 1
    assert result["rows"] == 3  # 标号行带 + 两行素材


def test_bg_color_auto_and_hex(tmp_path, sheet_path):
    # 留空自动取四角
    auto = _run(tmp_path, sheet_path, bg_color="")
    assert auto["count"] == 3

    # 十六进制等价写法
    hexdir = tmp_path / "hex"
    hexed = _run(tmp_path, sheet_path, bg_color="#0A0A0A", output_dir=str(hexdir))
    assert hexed["count"] == 3


def test_feather_and_padding(tmp_path, sheet_path):
    result = _run(tmp_path, sheet_path, feather=2, padding=1)
    assert result["count"] == 3

    by_name = {Path(p).name: p for p in result["paths"]}
    out = _read(by_name["sheet_r002c002.png"])
    # 外扩 padding 1 + 羽化余量 4 → 比硬边 bbox 各方向多 5px（贴格线方向除外）
    assert out.shape[:2] == (55 + 10, 58 + 10)
    # 羽化后边缘存在半透明像素
    alphas = out[:, :, 3]
    assert ((alphas > 0) & (alphas < 255)).any()


def test_invalid_params_raise(sheet_path):
    with pytest.raises(ValueError, match="image_path"):
        sprite_sheet_cut.handler({"image_path": ""}, context=None)
    with pytest.raises(ValueError, match="背景色"):
        sprite_sheet_cut.handler(
            {"image_path": str(sheet_path), "bg_color": "red"}, context=None
        )


def test_default_output_dir_is_sibling_cut_folder(tmp_path, sheet_path):
    result = _run(tmp_path, sheet_path, output_dir="")

    out = Path(result["output_dir"])
    assert out == sheet_path.parent / "sheet_cut"  # 图片名开头的新文件夹
    assert Path(result["paths"][0]).parent == out
    assert out.is_dir()


def test_folder_batch_mode(tmp_path, sheet_path):
    folder = tmp_path / "sheets"
    folder.mkdir()
    for name in ("a.png", "b.png"):
        ok, buf = cv2.imencode(".png", _build_sheet())
        assert ok
        buf.tofile(str(folder / name))
    # 非图片文件应被忽略；损坏图片应进入 errors 且不中断整体
    (folder / "notes.txt").write_text("not an image", encoding="utf-8")
    (folder / "bad.png").write_bytes(b"\x89PNG\r\n corrupted")

    result = _run(tmp_path, folder, image_path=str(folder))

    assert result["sheets"] == 3
    assert result["count"] == 6  # 两张正常图各切 3 张
    assert result["skipped"] == 2
    assert len(result["per_file"]) == 2
    assert len(result["errors"]) == 1
    assert "bad.png" in result["errors"][0]["image"]
    assert len(result["paths"]) == 6
    # 每张图输出到独立子目录
    out_dirs = {item["output_dir"] for item in result["per_file"]}
    assert len(out_dirs) == 2


def test_folder_without_images_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "doc.txt").write_text("hi", encoding="utf-8")
    with pytest.raises(ValueError, match="未找到图片"):
        sprite_sheet_cut.handler({"image_path": str(empty)}, context=None)


def test_schema_registered():
    from backend.core.registry import register_block

    register_block(sprite_sheet_cut.SCHEMA, sprite_sheet_cut.handler)
