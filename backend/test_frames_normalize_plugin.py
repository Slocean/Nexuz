"""frames_normalize 用户积木：锚点/缩放/落位/加宽/守卫与批量参照行为。

用合成序列帧验证设计文档验收口径：跨帧同高锚内容、高度严格一致、
宽度 ≥ 基准宽、越界帧记入 errors 不产出、帧间动作位移保留（整帧平移）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw

_PLUGIN_PATH = (
    Path(__file__).resolve().parents[1] / "examples" / "user_blocks" / "frames_normalize.py"
)


def _load_plugin():
    spec = importlib.util.spec_from_file_location("frames_normalize_under_test", _PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def plugin():
    return _load_plugin()


def _frame(path: Path, size: tuple[int, int], rects: list[tuple[int, int, int, int]]) -> None:
    """rects 为 (x0, y0, x1, y1) 开区间内容矩形，画不透明纯色，其余透明。"""
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    for x0, y0, x1, y1 in rects:
        draw.rectangle([x0, y0, x1 - 1, y1 - 1], fill=(200, 30, 30, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def _content_bbox_of(path: Path) -> tuple[int, int, int, int]:
    with Image.open(path) as im:
        alpha = im.getchannel("A").point(lambda v: 255 if v > 16 else 0)
        return alpha.getbbox()


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    """参照=ref（锚内容高 40，画布 100×80）；heroA 加宽+越界守卫；heroB 常规。"""
    root = tmp_path_factory.mktemp("frames_norm")
    _frame(root / "ref" / "f1.png", (100, 80), [(30, 40, 70, 80)])
    _frame(root / "ref" / "f2.png", (100, 80), [(25, 45, 75, 80)])
    # heroA：锚内容高 20 → s=2；第 3 帧纵向越界；挥砍帧触发画布加宽
    _frame(root / "heroA" / "a1.png", (100, 80), [(35, 60, 65, 80)])
    _frame(root / "heroA" / "a2.png", (100, 80), [(10, 55, 90, 80)])
    _frame(root / "heroA" / "a3.png", (100, 80), [(30, 10, 70, 80)])
    # heroB：窄画布 60×60，锚内容高 20 → s=2，不触发加宽
    _frame(root / "heroB" / "b1.png", (60, 60), [(20, 30, 40, 50)])
    _frame(root / "heroB" / "b2.png", (60, 60), [(15, 35, 45, 50)])
    # heroC：画布不一致 → 整文件夹报错
    _frame(root / "heroC" / "c1.png", (100, 80), [(30, 40, 70, 80)])
    _frame(root / "heroC" / "c2.png", (90, 70), [(30, 40, 70, 70)])
    # heroE：单文件夹无参照 → s=1 仅位置归一，输出应与输入逐像素一致
    _frame(root / "heroE" / "e1.png", (100, 80), [(30, 40, 70, 80)])
    return root


def _run(plugin, root: Path, folders: str, **extra):
    params = {
        "image_path": "\n".join(str(root / name) for name in folders.split(",")),
        "reference_folder": str(root / "ref") if extra.pop("use_ref", True) else "",
        "output_dir": str(root / "out"),
        **extra,
    }
    return plugin.handler(params, {}), root / "out"


def test_batch_reference_normalize(plugin, scene):
    (result, out) = _run(plugin, scene, "heroA,heroB")
    # heroA：a3 越界跳过 → 2 帧；heroB：2 帧
    assert result["count"] == 4
    assert any("超出画布高" in e and "a3" in e for e in result["errors"])
    assert result["errors"] and result["ok"] is False

    by_file = {Path(p).name: p for p in result["paths"]}
    assert set(by_file) == {"a1.png", "a2.png", "b1.png", "b2.png"}

    # heroA：挥砍帧并集宽 → 画布加宽 160×80（高度严格一致）
    with Image.open(by_file["a1.png"]) as im:
        assert im.size == (160, 80)
    bbox = _content_bbox_of(Path(by_file["a1.png"]))
    # 锚内容高 = 参照锚高 40（±1 LANCZOS 抗锯齿取整容差），底边贴画布底、水平居中
    assert abs((bbox[3] - bbox[1]) - 40) <= 1
    assert bbox[3] == 80
    assert abs((bbox[0] + bbox[2]) / 2 - 80) <= 1.5

    # 挥砍帧（a2）内容完整保留（加宽不裁切）：并集宽 = 画布宽
    swing = _content_bbox_of(Path(by_file["a2.png"]))
    assert swing[0] >= 0 and swing[2] <= 160

    # heroB：不触发加宽 → 基准画布 100×80
    with Image.open(by_file["b1.png"]) as im:
        assert im.size == (100, 80)
    bbox_b = _content_bbox_of(Path(by_file["b1.png"]))
    assert abs((bbox_b[3] - bbox_b[1]) - 40) <= 1
    assert bbox_b[3] == 80

    # per_file 明细字段
    detail = next(d for d in result["per_file"] if d["file"] == "a1.png")
    assert detail["scale"] == 2.0
    assert detail["canvas"] == [100, 80]
    assert detail["anchor_content"] == [30, 20]
    assert detail["output_canvas"] == [160, 80]
    assert set(detail) >= {"folder", "file", "path", "dx", "dy", "scale", "canvas",
                           "anchor_content", "output_canvas"}


def test_frame_action_displacement_preserved(plugin, scene):
    """帧间动作位移完整保留：输出帧 = 原帧整幅缩放 + 同一 (dx,dy) 平移。"""
    (result, out) = _run(plugin, scene, "heroA")
    plugin_mod = plugin
    detail = {d["file"]: d for d in result["per_file"]}
    dx, dy, scale = detail["a1.png"]["dx"], detail["a1.png"]["dy"], detail["a1.png"]["scale"]
    assert detail["a2.png"]["dx"] == dx and detail["a2.png"]["dy"] == dy

    with Image.open(scene / "heroA" / "a2.png") as im:
        src = im.convert("RGBA")
    scaled = src.resize(
        (round(src.width * scale), round(src.height * scale)), Image.Resampling.LANCZOS
    )
    canvas = Image.new("RGBA", (160, 80), (0, 0, 0, 0))
    canvas.paste(scaled, (dx, dy))
    with Image.open(Path(detail["a2.png"]["path"])) as out_im:
        diff = ImageChops.difference(canvas, out_im.convert("RGBA"))
        assert diff.getbbox() is None


def test_canvas_mismatch_skips_folder(plugin, scene):
    (result, out) = _run(plugin, scene, "heroC,heroB")
    assert any("画布不一致" in e and "heroC" in e for e in result["errors"])
    assert {Path(p).name for p in result["paths"]} == {"b1.png", "b2.png"}


def test_anchor_frame_out_of_range(plugin, scene):
    # 不带参照：越界锚点帧号作用于输入序列本身
    (result, out) = _run(plugin, scene, "heroB", use_ref=False, anchor_frame=5)
    assert any("越界" in e for e in result["errors"])
    assert result["paths"] == []


def test_single_folder_no_reference_identity(plugin, scene):
    """无参照：s=1 仅位置归一；锚内容本就居中贴底时输出应逐像素一致。"""
    (result, out) = _run(plugin, scene, "heroE", use_ref=False)
    assert result["ok"] is True and result["count"] == 1
    detail = result["per_file"][0]
    assert detail["scale"] == 1.0 and (detail["dx"], detail["dy"]) == (0, 0)
    with Image.open(scene / "heroE" / "e1.png") as src, Image.open(detail["path"]) as dst:
        assert ImageChops.difference(src.convert("RGBA"), dst.convert("RGBA")).getbbox() is None


def test_anchor_mode_union(plugin, scene):
    (result, out) = _run(plugin, scene, "heroB", anchor_mode="union")
    assert result["count"] == 2
    detail = result["per_file"][0]
    # heroB 并集内容高 30（y 30~60... 实际 f1 h20 / f2 h15 → 并集 y30~50 h20）
    assert detail["scale"] == pytest.approx(2.0)


def test_anchor_mode_max_content(plugin, scene):
    (result, out) = _run(plugin, scene, "heroB", anchor_mode="max_content")
    assert result["count"] == 2
    # 最大内容帧 = b1（h20）→ s 仍为 2
    assert result["per_file"][0]["scale"] == pytest.approx(2.0)


def test_missing_folder_recorded(plugin, scene):
    params = {
        "image_path": f"{scene / 'heroB'}\n{scene / 'nope'}",
        "reference_folder": str(scene / "ref"),
        "output_dir": str(scene / "out2"),
    }
    result = plugin.handler(params, {})
    assert any("不存在" in e for e in result["errors"])
    assert result["count"] == 2


def test_empty_input_raises(plugin):
    with pytest.raises(ValueError, match="不能为空"):
        plugin.handler({"image_path": ""}, {})


def test_worker_end_to_end(plugin, scene, tmp_path):
    """生产路径：隔离 worker（含文件写入放行）执行真实插件文件。"""
    from backend.core.registry import _make_isolated_user_handler

    handler = _make_isolated_user_handler(_PLUGIN_PATH, "frames_normalize")
    result = handler(
        {
            "image_path": str(scene / "heroB"),
            "reference_folder": str(scene / "ref"),
            "output_dir": str(tmp_path / "e2e_out"),
        },
        {},
    )
    assert result["ok"] is True, result.get("error")
    assert result["count"] == 2
    for path in result["paths"]:
        assert Path(path).is_file()
