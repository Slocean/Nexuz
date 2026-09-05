"""image_diff 用户积木：配对/容差/占比上限/可视化/尺寸守卫与 worker 路径。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

_PLUGIN_PATH = (
    Path(__file__).resolve().parents[1] / "examples" / "user_blocks" / "image_diff.py"
)


def _load_plugin():
    spec = importlib.util.spec_from_file_location("image_diff_under_test", _PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def plugin():
    return _load_plugin()


def _frame(path: Path, paint: bool, size=(100, 80)) -> None:
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    if paint:
        ImageDraw.Draw(im).rectangle([30, 40, 69, 79], fill=(200, 30, 30, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    root = tmp_path_factory.mktemp("image_diff")
    # 基线组与 identical 组：逐像素一致
    for d in ("base", "same"):
        for i in (1, 2, 3):
            _frame(root / d / f"f{i}.png", paint=True)
    # 改动组：f1 单像素涂改、f2 未动、f3 尺寸不同
    changed = root / "changed"
    _frame(changed / "f1.png", paint=True)
    im = Image.open(changed / "f1.png")
    px = im.load()
    px[50, 50] = (0, 255, 0, 255)
    im.save(changed / "f1.png")
    _frame(changed / "f2.png", paint=True)
    _frame(changed / "f3.png", paint=True, size=(50, 40))
    return root


def test_identical_pair(plugin, scene):
    result = plugin.handler(
        {"image_path_a": str(scene / "base" / "f1.png"), "image_path_b": str(scene / "same" / "f1.png")},
        {},
    )
    assert result["ok"] is True and result["identical"] is True
    assert result["max_ratio"] == 0 and result["pairs"] == 1


def test_threshold_tolerance(plugin, scene, tmp_path):
    a = scene / "base" / "f1.png"
    tweaked = tmp_path / "tweaked.png"
    im = Image.open(a)
    px = im.load()
    px[50, 50] = (205, 35, 30, 255)  # 每通道差 5
    im.save(tweaked)
    params = {"image_path_a": str(a), "image_path_b": str(tweaked)}
    r_exact = plugin.handler({**params, "diff_image": "no"}, {})
    assert r_exact["identical"] is False and r_exact["max_ratio"] > 0
    r_tol = plugin.handler({**params, "threshold": 10, "diff_image": "no"}, {})
    assert r_tol["identical"] is True and r_tol["ok"] is True


def test_single_pixel_detected_with_visualization(plugin, scene, tmp_path):
    result = plugin.handler(
        {
            "image_path_a": str(scene / "base" / "f1.png"),
            "image_path_b": str(scene / "changed" / "f1.png"),
            "output_dir": str(tmp_path),
        },
        {},
    )
    assert result["ok"] is False  # fail_ratio=0 任何差异都记
    pair = result["per_pair"][0]
    assert pair["diff_pixels"] == 1 and pair["identical"] is False
    vis = Path(pair["diff_image"])
    assert vis.is_file()
    arr = np.array(Image.open(vis).convert("RGBA"))
    assert (255, 0, 0, 255) in map(tuple, arr.reshape(-1, 4)[::37][:200]) or (arr == (255, 0, 0, 255)).any()


def test_fail_ratio(plugin, scene):
    result = plugin.handler(
        {
            "image_path_a": str(scene / "base" / "f1.png"),
            "image_path_b": str(scene / "changed" / "f1.png"),
            "fail_ratio": 1,
            "diff_image": "no",
        },
        {},
    )
    assert result["ok"] is True and result["identical"] is False  # 1/8000 < 1% 不记错误


def test_folder_pairing_and_size_mismatch(plugin, scene):
    result = plugin.handler(
        {
            "image_path_a": str(scene / "base"),
            "image_path_b": str(scene / "changed"),
            "diff_image": "no",
        },
        {},
    )
    assert result["ok"] is False
    joined = "\n".join(result["errors"])
    assert "尺寸不一致" in joined and "f3.png" in joined
    assert result["pairs"] == 2  # f3 尺寸不一致不计入配对
    f1 = next(p for p in result["per_pair"] if p["pair"] == "f1.png")
    assert f1["diff_pixels"] == 1


def test_folder_stray_files(plugin, scene, tmp_path):
    stray = tmp_path / "stray"
    _frame(stray / "f1.png", paint=True)
    _frame(stray / "extra.png", paint=True)
    result = plugin.handler(
        {"image_path_a": str(scene / "base"), "image_path_b": str(stray), "diff_image": "no"},
        {},
    )
    assert result["ok"] is False
    joined = "\n".join(result["errors"])
    assert "B 侧缺少" in joined and "A 侧缺少" in joined


def test_mixed_sides_raises(plugin, scene):
    with pytest.raises(ValueError, match="同为单张图片或同为文件夹"):
        plugin.handler(
            {"image_path_a": str(scene / "base" / "f1.png"), "image_path_b": str(scene / "changed")},
            {},
        )


def test_empty_input_raises(plugin):
    with pytest.raises(ValueError, match="不能为空"):
        plugin.handler({"image_path_a": "", "image_path_b": ""}, {})


def test_worker_end_to_end(plugin, scene, tmp_path):
    from backend.core.registry import _make_isolated_user_handler

    handler = _make_isolated_user_handler(_PLUGIN_PATH, "image_diff")
    result = handler(
        {
            "image_path_a": str(scene / "base" / "f1.png"),
            "image_path_b": str(scene / "same" / "f1.png"),
            "diff_image": "no",
        },
        {},
    )
    assert result["ok"] is True and result["identical"] is True, result.get("error")
