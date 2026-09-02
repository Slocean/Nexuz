from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.blocks import transparent_cut


def _build_sheet() -> np.ndarray:
    """多素材透明图（200x200，BGRA，背景全透明）：

    - 素材A (20..80, 20..80)：不透明色块，内部挖透明孔洞（须保留）
    - 素材B (120..160, 20..60)：与 A 之间有透明间隙
    - 素材C (120..180, 120..180)
    - 噪点 (5..8, 5..8)：3x3，供 min_area 自动过滤
    - 抗锯齿条 (90..96, 90..110)：alpha=5，低于默认阈值，供阈值测试
    """
    img = np.zeros((200, 200, 4), dtype=np.uint8)
    img[:, :, :3] = (30, 120, 200)
    img[20:80, 20:80, 3] = 255  # 素材A
    img[35:50, 35:50, 3] = 0  # A 的内部透明孔洞
    img[120:160, 20:60, 3] = 255  # 素材B
    img[120:180, 120:180, 3] = 255  # 素材C
    img[5:8, 5:8, 3] = 255  # 噪点
    img[90:96, 90:110, 3] = 5  # 抗锯齿条（alpha=5）
    return img


def _build_gap_sheet() -> np.ndarray:
    """两块素材仅隔 2px 透明缝（80x160）。"""
    img = np.zeros((80, 160, 4), dtype=np.uint8)
    img[:, :, :3] = (30, 120, 200)
    img[20:80, 20:80, 3] = 255
    img[20:80, 82:140, 3] = 255  # 与左侧间隔 cols 80..82 共 2px
    return img


def _build_two_sprites() -> np.ndarray:
    """一大一小两个素材（100x100），供手动 min_area 过滤。"""
    img = np.zeros((100, 100, 4), dtype=np.uint8)
    img[:, :, :3] = (30, 120, 200)
    img[10:70, 10:70, 3] = 255  # 60x60
    img[80:90, 80:90, 3] = 255  # 10x10，像素面积 100
    return img


def _build_overlap_sheet() -> np.ndarray:
    """L 形大素材 + 完全落在其包围盒内的小素材（200x200）。

    L 形像素面积 8700，包围盒 (20,20)-(180,180)；小素材 (100..140)^2
    与 L 像素不相连，但包围盒被 L 完全包含，用于验证切分形状差异。
    """
    img = np.zeros((200, 200, 4), dtype=np.uint8)
    img[:, :, :3] = (30, 120, 200)
    img[20:180, 20:50, 3] = 255  # L 竖臂
    img[20:50, 20:180, 3] = 255  # L 横臂
    img[100:140, 100:140, 3] = 255  # 小素材，落在 L 包围盒内部
    return img


def _encode(path, img) -> Path:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    buf.tofile(str(path))
    return path


@pytest.fixture()
def sheet_path(tmp_path):
    return _encode(tmp_path / "sheet.png", _build_sheet())


def _read(path) -> np.ndarray:
    data = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    assert data is not None and data.ndim == 3 and data.shape[2] == 4
    return data


BASE_PARAMS = {
    "cut_mode": "components",
    "alpha_threshold": 8,
    "gap_tolerance": 0,
    "min_area": 0,
    "padding": 0,
    "feather": 0,
    "name_prefix": "",
}


def _run(tmp_path, sheet_path, **overrides):
    params = {
        **BASE_PARAMS,
        "image_path": str(sheet_path),
        "output_dir": str(tmp_path / "out"),
        **overrides,
    }
    return transparent_cut.handler(params, context=None)


def test_components_mode_full_pipeline(tmp_path, sheet_path):
    result = _run(tmp_path, sheet_path)

    assert result["count"] == 3
    assert result["skipped"] == 1  # 3x3 噪点被自动 min_area 过滤
    assert Path(result["output_dir"]).is_dir()

    by_name = {Path(p).name: p for p in result["paths"]}
    # 阅读顺序命名：A → B → C
    assert list(result["paths"]) == [
        str(Path(result["output_dir"]) / n)
        for n in ("sheet_001.png", "sheet_002.png", "sheet_003.png")
    ]

    # 素材A：紧贴包围盒，内部透明孔洞保留
    out = _read(by_name["sheet_001.png"])
    assert out.shape[:2] == (60, 60)
    assert out[20, 20, 3] == 0  # 孔洞（原图 35..50 → 输出 15..30）
    assert out[5, 5, 3] == 255  # 孔洞周边不透明
    assert tuple(out[5, 5, :3]) == (30, 120, 200)  # BGR 原色

    # 素材B / C
    assert _read(by_name["sheet_002.png"]).shape[:2] == (40, 40)
    assert _read(by_name["sheet_003.png"]).shape[:2] == (60, 60)


def test_projection_mode(tmp_path, sheet_path):
    result = _run(tmp_path, sheet_path, cut_mode="projection")

    assert result["count"] == 3
    # 行带：噪点自成一带（其素材被面积过滤）+ A 一行 + B/C 重叠合并一行
    assert result["skipped"] == 1
    assert result["per_file"][0]["rows"] == 3
    assert result["per_file"][0]["cols"] == 2

    by_name = {Path(p).name: p for p in result["paths"]}
    assert set(by_name) == {"sheet_r001c000.png", "sheet_r002c000.png", "sheet_r002c001.png"}

    # A：行带×列带紧贴裁切，孔洞保留
    out = _read(by_name["sheet_r001c000.png"])
    assert out.shape[:2] == (60, 60)
    assert out[20, 20, 3] == 0

    # B：y 取整个行带 [120,180)，x 取列带 → 含底部透明区
    out = _read(by_name["sheet_r002c000.png"])
    assert out.shape[:2] == (60, 40)
    assert out[10, 10, 3] == 255  # B 主体
    assert out[50, 10, 3] == 0  # 行带底部超出 B 的部分保持透明


def test_alpha_threshold(tmp_path, sheet_path):
    # 默认阈值 8：alpha=5 的抗锯齿条不可见
    default = _run(tmp_path, sheet_path)
    assert default["count"] == 3

    # 降低阈值：抗锯齿条（120px）成为第 4 个素材（阅读顺序排第 2）
    low = _run(tmp_path, sheet_path, alpha_threshold=3)
    assert low["count"] == 4
    assert {Path(p).name for p in low["paths"]} == {
        "sheet_001.png",
        "sheet_002.png",
        "sheet_003.png",
        "sheet_004.png",
    }


def test_gap_tolerance(tmp_path, sheet_path):
    gap_path = _encode(sheet_path.parent / "gap.png", _build_gap_sheet())

    # 不容忍：2px 透明缝切开两块
    split = _run(tmp_path, gap_path)
    assert split["count"] == 2
    # 容忍 4px：连通域闭运算粘连 / 投影条带合并，均输出 1 张
    merged_c = _run(tmp_path, gap_path, gap_tolerance=4)
    assert merged_c["count"] == 1
    merged_p = _run(tmp_path, gap_path, gap_tolerance=4, cut_mode="projection")
    assert merged_p["count"] == 1
    # 粘连后包围盒覆盖两块素材
    out = _read(merged_c["paths"][0])
    assert out.shape[:2] == (60, 120)


def test_shape_mode_rect_keeps_foreign_pixels(tmp_path):
    """规则矩形：L 的包围盒包含小素材，小素材像素混进 L 的切图。"""
    p = _encode(tmp_path / "overlap.png", _build_overlap_sheet())

    result = _run(tmp_path, p, shape_mode="rect")
    assert result["count"] == 2

    l_img = _read(result["paths"][0])  # 阅读顺序：L 在前
    assert l_img.shape[:2] == (160, 160)
    assert l_img[80, 80, 3] == 255  # 小素材像素被混入
    assert int((l_img[:, :, 3] > 0).sum()) == 8700 + 1600


def test_shape_mode_irregular_cuts_own_pixels_only(tmp_path):
    """不规则形状：每张切图只保留本素材像素，重叠素材不互相混入。"""
    p = _encode(tmp_path / "overlap.png", _build_overlap_sheet())

    result = _run(tmp_path, p, shape_mode="irregular")
    assert result["count"] == 2  # 分组与规则矩形一致，仅像素归属不同

    l_img = _read(result["paths"][0])
    assert l_img.shape[:2] == (160, 160)
    assert l_img[80, 80, 3] == 0  # 小素材位置抹为透明
    assert l_img[5, 5, 3] == 255  # 自身像素保留
    assert int((l_img[:, :, 3] > 0).sum()) == 8700  # 只剩 L 自身

    small = _read(result["paths"][1])
    assert small.shape[:2] == (40, 40)
    assert int((small[:, :, 3] > 0).sum()) == 1600


def test_shape_mode_irregular_with_gap_tolerance(tmp_path, sheet_path):
    """闭运算粘连的贴身部件同属一个连通域，两块像素都保留。"""
    gap_path = _encode(sheet_path.parent / "gap.png", _build_gap_sheet())

    result = _run(tmp_path, gap_path, gap_tolerance=4, shape_mode="irregular")
    assert result["count"] == 1

    out = _read(result["paths"][0])
    assert out.shape[:2] == (60, 120)
    assert out[10, 10, 3] == 255  # 左块
    assert out[10, 60, 3] == 0  # 原 2px 透明缝（闭运算填充区 alpha 仍为 0）
    assert out[10, 70, 3] == 255  # 右块


def test_shape_mode_irregular_with_padding_feather(tmp_path):
    p = _encode(tmp_path / "overlap.png", _build_overlap_sheet())

    result = _run(tmp_path, p, shape_mode="irregular", padding=2, feather=2)
    l_img = _read(result["paths"][0])
    # 外扩 padding 2 + 羽化余量 4 → 每边 6px
    assert l_img.shape[:2] == (160 + 12, 160 + 12)
    assert l_img[80 + 6, 80 + 6, 3] == 0  # 小素材仍被抹除（含外扩偏移）
    alphas = l_img[:, :, 3]
    assert ((alphas > 0) & (alphas < 255)).any()  # 自身边缘正常羽化


def test_shape_mode_ignored_in_projection(tmp_path, sheet_path):
    """行列投影按条带切分本就不会混入邻居，形状选项不影响结果。"""
    result = _run(tmp_path, sheet_path, cut_mode="projection", shape_mode="irregular")
    assert result["count"] == 3


def test_single_sprite(tmp_path):
    img = np.zeros((50, 50, 4), dtype=np.uint8)
    img[:, :, :3] = (30, 120, 200)
    img[10:40, 10:40, 3] = 255
    p = _encode(tmp_path / "single.png", img)

    result = _run(tmp_path, p)
    assert result["count"] == 1
    assert _read(result["paths"][0]).shape[:2] == (30, 30)


def test_no_alpha_raises(tmp_path, sheet_path):
    bgr = np.full((40, 40, 3), 100, dtype=np.uint8)
    no_alpha = tmp_path / "flat.png"
    ok, buf = cv2.imencode(".png", bgr)
    assert ok
    buf.tofile(str(no_alpha))

    # 单图直接报错，并引导使用精灵图节点
    with pytest.raises(ValueError, match="Alpha"):
        transparent_cut.handler({"image_path": str(no_alpha)}, context=None)

    # 批量模式：进 errors 且不中断其他图
    result = _run(tmp_path, sheet_path, image_path=str(no_alpha.parent), output_dir="")
    assert any("flat.png" in e["image"] for e in result["errors"])
    assert result["count"] >= 1  # 同文件夹其他图正常输出


def test_min_area_filter_and_skipped(tmp_path):
    p = _encode(tmp_path / "two.png", _build_two_sprites())

    # 手动阈值：10x10（面积 100）被过滤
    result = _run(tmp_path, p, min_area=150)
    assert result["count"] == 1
    assert result["skipped"] == 1
    assert Path(result["paths"][0]).name == "two_001.png"


def test_padding_and_feather(tmp_path, sheet_path):
    result = _run(tmp_path, sheet_path, padding=2, feather=2)
    assert result["count"] == 3

    by_name = {Path(p).name: p for p in result["paths"]}
    out = _read(by_name["sheet_001.png"])
    # 素材A 硬边 bbox 60x60，外扩 padding 2 + 羽化余量 4 → 每边 6px
    assert out.shape[:2] == (60 + 12, 60 + 12)
    # 羽化后边缘存在半透明像素
    alphas = out[:, :, 3]
    assert ((alphas > 0) & (alphas < 255)).any()


def test_name_prefix(tmp_path, sheet_path):
    result = _run(tmp_path, sheet_path, name_prefix="icon")
    assert {Path(p).name for p in result["paths"]} == {
        "icon_001.png",
        "icon_002.png",
        "icon_003.png",
    }


def test_default_output_dir_is_sibling_cut_folder(tmp_path, sheet_path):
    result = _run(tmp_path, sheet_path, output_dir="")

    out = Path(result["output_dir"])
    assert out == sheet_path.parent / "sheet_cut"  # 图片名开头的新文件夹
    assert Path(result["paths"][0]).parent == out
    assert out.is_dir()


def test_empty_sheet_raises(tmp_path):
    img = np.zeros((30, 30, 4), dtype=np.uint8)
    img[:, :, :3] = (30, 120, 200)
    p = _encode(tmp_path / "empty.png", img)

    with pytest.raises(ValueError, match="未检测到"):
        transparent_cut.handler(
            {"image_path": str(p), "output_dir": str(tmp_path / "out")}, context=None
        )


def test_folder_batch_mode(tmp_path, sheet_path):
    folder = tmp_path / "sheets"
    folder.mkdir()
    for name in ("a.png", "b.png"):
        _encode(folder / name, _build_sheet())
    # 无 alpha 通道的图进 errors；非图片文件被忽略；损坏图片进 errors 且不中断
    bgr = np.full((40, 40, 3), 100, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", bgr)
    assert ok
    buf.tofile(str(folder / "flat.png"))
    (folder / "notes.txt").write_text("not an image", encoding="utf-8")
    (folder / "bad.png").write_bytes(b"\x89PNG\r\n corrupted")

    result = _run(tmp_path, folder, image_path=str(folder), output_dir="")

    assert result["sheets"] == 4  # a/b/flat/bad 共 4 张图片被扫描
    assert result["count"] == 6  # 两张正常图各切 3 张
    assert result["skipped"] == 2
    assert len(result["per_file"]) == 2
    assert len(result["errors"]) == 2
    error_names = " ".join(e["image"] for e in result["errors"])
    assert "flat.png" in error_names and "bad.png" in error_names
    assert len(result["paths"]) == 6
    # 每张图输出到独立子目录
    out_dirs = {item["output_dir"] for item in result["per_file"]}
    assert len(out_dirs) == 2


def test_folder_without_images_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "doc.txt").write_text("hi", encoding="utf-8")
    with pytest.raises(ValueError, match="未找到图片"):
        transparent_cut.handler({"image_path": str(empty)}, context=None)


def test_invalid_params_raise(sheet_path):
    with pytest.raises(ValueError, match="image_path"):
        transparent_cut.handler({"image_path": ""}, context=None)
    with pytest.raises(FileNotFoundError):
        transparent_cut.handler(
            {"image_path": str(sheet_path.parent / "missing.png")}, context=None
        )


def test_schema_registered():
    from backend.core.registry import register_block

    register_block(transparent_cut.SCHEMA, transparent_cut.handler)
