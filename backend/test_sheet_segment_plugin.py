"""sheet_segment 用户积木：自动帧数检测/漂移鲁棒切分/守卫/命名与批量行为。

用合成合板验证设计文档验收口径：帧位漂移下越格披风不被网格切线切碎（完整
出现在属主帧）、自动帧数检测与构造一致、行带数/宽高比守卫记入 errors 不产出
损坏帧、紧裁与行带画布两种输出、worker 生产路径（含文件写入放行）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

_PLUGIN_PATH = (
    Path(__file__).resolve().parents[1] / "examples" / "user_blocks" / "sheet_segment.py"
)


def _load_plugin():
    spec = importlib.util.spec_from_file_location("sheet_segment_under_test", _PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def plugin():
    return _load_plugin()


# 合板几何：2 行 × 4 帧，格宽 200、内容行高 200（身体 y 100..300）、行间空 100
_CELL_W = 200
_SHEET_W = _CELL_W * 4
_ROW_H = 300
_ROW_GAP = 100
_NF = 4
# 帧位漂移（±8px：格线 200(j+1) 落在披风 [c+40, c+110] 内，固定网格必切碎披风；
# 第 4 帧漂移 +8 使披风伸出画布右缘被裁）
_DRIFTS = (-8, 8, -8, 8)
_BODY = (200, 40, 40, 255)
_BODY_UP = (40, 90, 200, 255)
# 每帧披风独立色，便于断言像素归属
_CAPES = [(250, 180, 60, 255), (90, 220, 90, 255), (220, 90, 220, 255), (90, 220, 220, 255)]
# 帧内容：身体 80×200 + 越格披风 70×50 → 并集 150×200；末帧披风被画布裁到 52 宽
_FULL = (150, 200)
_CLIPPED = (132, 200)
_CLIPPED_CAPE_W = _SHEET_W - (3 * _CELL_W + 100 + _DRIFTS[3] + 40)


def _draw_row(draw, y0: int, body_color) -> None:
    for j in range(_NF):
        c = j * _CELL_W + 100 + _DRIFTS[j]
        draw.rectangle([c - 40, y0 + 100, c + 40 - 1, y0 + _ROW_H - 1], fill=body_color)
        # 披风向右越格：跨过格线但与邻帧身体保持间隙（像素不粘连）
        draw.rectangle([c + 40, y0 + 120, c + 110 - 1, y0 + 170 - 1], fill=_CAPES[j])


def _sheet(path: Path) -> Path:
    h = 2 * _ROW_H + _ROW_GAP
    im = Image.new("RGBA", (_SHEET_W, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    _draw_row(draw, 0, _BODY)
    _draw_row(draw, _ROW_H + _ROW_GAP, _BODY_UP)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


def _count_color(path: Path, color) -> int:
    arr = np.array(Image.open(path).convert("RGBA"))
    return int((arr == tuple(color)).all(axis=2).sum())


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    root = tmp_path_factory.mktemp("sheet_seg")
    sheets = [_sheet(root / "sheetA.png"), _sheet(root / "sheetB.png")]
    return root, sheets


def _run(plugin, root: Path, sheets, **extra):
    params = {
        "image_path": "\n".join(str(s) for s in sheets),
        "output_dir": str(root / "out"),
        **extra,
    }
    return plugin.handler(params, {})


def test_batch_auto_detect_and_cape_ownership(plugin, scene):
    """自动帧数=4/行；漂移合板上越格披风完整落在属主帧（固定网格切线必切碎）。"""
    root, sheets = scene
    result = _run(plugin, root, sheets)
    assert result["ok"] is True, result["errors"]
    assert result["frames"] == 16 and result["sheets"] == 2

    # sheetA down 行：4 帧；紧裁画布 = 身体+披风并集 150×200（末帧披风被画布裁到 132）
    row_dir = root / "out" / "sheetA" / "down"
    files = sorted(row_dir.glob("down_*.png"))
    assert [f.name for f in files] == [f"down_{i:02d}.png" for i in range(1, 5)]
    expected_sizes = [_FULL, _FULL, _FULL, _CLIPPED]
    for f, size in zip(files, expected_sizes):
        assert Image.open(f).size == size, f.name
    # 披风完整（整块在属主帧内，未被网格切线切碎）；末帧披风按画布缘裁剩 52 宽
    for j, f in enumerate(files):
        cape_w = 70 if j < 3 else _CLIPPED_CAPE_W
        assert _count_color(f, _CAPES[j]) == cape_w * 50, f.name
    # 帧内无邻帧披风色
    for j, f in enumerate(files):
        for k in range(_NF):
            if k != j:
                assert _count_color(f, _CAPES[k]) == 0, (f.name, k)
    # up 行同样成立
    up_files = sorted((root / "out" / "sheetA" / "up").glob("up_*.png"))
    for j, f in enumerate(up_files):
        cape_w = 70 if j < 3 else _CLIPPED_CAPE_W
        assert _count_color(f, _CAPES[j]) == cape_w * 50, f.name

    # 多张合板按图名分子目录
    assert (root / "out" / "sheetB" / "down" / "down_01.png").is_file()
    detail = result["per_row"][0]
    assert detail["sheet"] == "sheetA.png"
    assert detail["frame_count"] == 4 and detail["strategy"] == "watershed"
    assert set(detail) >= {"label", "frames", "strategy", "sizes", "boxes", "sheet", "frame_count"}


def test_rows_mismatch_records_error(plugin, scene):
    root, sheets = scene
    result = _run(plugin, root, sheets[:1], rows=3)
    assert result["paths"] == [] and result["frames"] == 0
    assert any("行带数" in e and "sheetA.png" in e for e in result["errors"])
    assert result["ok"] is False


def test_manual_frames_per_row_and_labels(plugin, scene):
    root, sheets = scene
    result = _run(
        plugin, root, sheets[:1], frames_per_row=_NF, direction_rows="walk_down,walk_up"
    )
    assert result["ok"] is True, result["errors"]
    names = {Path(p).name for p in result["paths"]}
    assert names == {f"walk_down_{i:02d}.png" for i in range(1, 5)} | {
        f"walk_up_{i:02d}.png" for i in range(1, 5)
    }
    assert {Path(p).parent.name for p in result["paths"]} == {"walk_down", "walk_up"}


def test_duplicate_labels_raises(plugin):
    with pytest.raises(ValueError, match="重复"):
        plugin.handler({"image_path": "x.png", "direction_rows": "down,down"}, {})


def test_tight_crop_no_keeps_band_canvas(plugin, scene):
    """tight_crop=no：保留行带画布（内容行高 200 ± 2px 边距），内容留在原位。"""
    root, sheets = scene
    result = _run(plugin, root, sheets[:1], tight_crop="no")
    assert result["ok"] is True, result["errors"]
    out = Path(result["paths"][0])
    with Image.open(out) as im:
        assert im.size == (_SHEET_W, (_ROW_H - 100) + 2 * 2)
        arr = np.array(im.convert("RGBA"))
    # 第 1 帧披风色像素质心 x 与原合板一致（c=100-8+75=167）
    xs = np.where((arr == tuple(_CAPES[0])).all(axis=2))
    assert abs(float(xs[1].mean()) - 167.0) <= 1.0


def test_aspect_guard(plugin, scene):
    """宽高比守卫：常规帧 150/200=0.75、末帧被画布裁到 132/200=0.66；上限 0.7
    时每行仅末帧存活，0.8 全过。"""
    root, sheets = scene
    result = _run(plugin, root, sheets[:1], max_aspect=0.7)
    assert result["frames"] == 2  # 每行各存活 1 帧
    assert any("宽高比超限" in e for e in result["errors"])
    result2 = _run(plugin, root, sheets[:1], max_aspect=0.8)
    assert result2["ok"] is True and result2["frames"] == 8


def test_detect_frame_count_split_feet_no_false_positive(plugin):
    """脚部每帧分裂成两块的行带不得误判出双倍帧数（宁报帧数不明）。"""
    # 8 个精灵、每个脚区两块（间距 40 / 跨步 250 交替），任何候选都无法同时
    # 通过「组件全认领 + 帧中心等距」→ 应返回 None
    band = np.zeros((120, 2000), dtype=bool)
    for k in range(8):
        base = k * 250 + 100
        band[60:, base - 15 : base + 15] = True
        band[60:, base + 25 : base + 55] = True
    assert plugin._detect_frame_count(band) is None


def test_gap_path_stays_in_background(plugin):
    """缝线 DP：蜿蜒背景缝里穿出的路径应全程落在背景内。"""
    H, W = 60, 80
    mask = np.ones((H, W), dtype=np.uint8)  # 1=前景
    # 蜿蜒缝须落在 2px 偶数网格上（缝道状态空间即该网格）；1px 奇数缝属于
    # 「整行堵死、+50 罚打穿」的设计行为，不在本用例范围
    for y in range(H):
        mask[y, 30 + 2 * ((y // 4) % 3)] = 0
    path = plugin._gap_path(mask, 32, max_dev=10)
    assert path is not None and len(path) == H
    for y, x in enumerate(path):
        assert mask[y, x] == 0, (y, x)


def test_missing_and_empty_inputs(plugin):
    with pytest.raises(ValueError, match="不能为空"):
        plugin.handler({"image_path": ""}, {})
    with pytest.raises(FileNotFoundError):
        plugin.handler({"image_path": "nope.png"}, {})


def test_worker_end_to_end(plugin, scene, tmp_path):
    """生产路径：隔离 worker（含文件写入放行）执行真实插件文件。"""
    from backend.core.registry import _make_isolated_user_handler

    root, sheets = scene
    handler = _make_isolated_user_handler(_PLUGIN_PATH, "sheet_segment")
    result = handler(
        {
            "image_path": str(sheets[0]),
            "frames_per_row": _NF,
            "output_dir": str(tmp_path / "e2e_out"),
        },
        {},
    )
    assert result["ok"] is True, result.get("error")
    assert result["frames"] == 8
    for path in result["paths"]:
        assert Path(path).is_file()
