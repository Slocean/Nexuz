"""sheet_contact 用户积木：网格拼图尺寸/底色/缩放/标注/输出命名与 worker 路径。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

_PLUGIN_PATH = (
    Path(__file__).resolve().parents[1] / "examples" / "user_blocks" / "sheet_contact.py"
)


def _load_plugin():
    spec = importlib.util.spec_from_file_location("sheet_contact_under_test", _PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def plugin():
    return _load_plugin()


def _frame(path: Path, size: tuple[int, int], color=(200, 30, 30, 255)) -> None:
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle([0, 0, size[0] - 1, size[1] - 1], fill=color)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    root = tmp_path_factory.mktemp("sheet_contact")
    hero = root / "heroA"
    for i in range(1, 6):  # 5 帧，第 2 帧更大（格子取组内最大）
        _frame(hero / f"f{i:02d}.png", (60, 80) if i != 2 else (80, 100))
    return root


def _run(plugin, root: Path, image_path: str, **extra):
    params = {"image_path": image_path, **extra}
    return plugin.handler(params, {})


def test_single_folder_default(plugin, scene):
    result = _run(plugin, scene, str(scene / "heroA"))
    assert result["ok"] is True, result["errors"]
    assert result["count"] == 1
    out = Path(result["paths"][0])
    assert out.name == "heroA_contact.png"
    # 单行铺开：5 × 80 宽（格子取最大帧 80×100）
    with Image.open(out) as im:
        assert im.size == (5 * 80, 100)
        # 深灰底
        assert im.getpixel((im.width - 1, im.height - 1))[:3] == (30, 30, 30)
    assert result["per_file"][0]["frames"] == 5


def test_columns_wrap_and_scale(plugin, scene):
    result = _run(plugin, scene, str(scene / "heroA"), columns=2, cell_scale=50)
    out = Path(result["paths"][0])
    with Image.open(out) as im:
        # 每格 40×50，2 列 3 行
        assert im.size == (2 * 40, 3 * 50)


def test_checker_background(plugin, scene):
    result = _run(plugin, scene, str(scene / "heroA"), background="checker")
    out = Path(result["paths"][0])
    with Image.open(out) as im:
        # 采样第一格右缘（帧宽 60 < 格宽 80，右缘是背景）
        px = im.getpixel((79, 0))
        assert px[:3] in ((204, 204, 204), (255, 255, 255))


def test_loose_files_single_sheet(plugin, scene):
    files = "\n".join(str(p) for p in sorted((scene / "heroA").glob("*.png")))
    result = _run(plugin, scene, files)
    assert result["ok"] is True, result["errors"]
    assert result["count"] == 1
    assert Path(result["paths"][0]).name == "contact.png"


def test_rerun_ignores_own_output(plugin, scene):
    """输出与输入同目录：二次运行不得把上次的拼图当成帧（回归 400x150 事故）。"""
    _run(plugin, scene, str(scene / "heroA"))
    result2 = _run(plugin, scene, str(scene / "heroA"))
    assert result2["per_file"][0]["frames"] == 5
    with Image.open(result2["paths"][0]) as im:
        assert im.size == (5 * 80, 100)


def test_output_dir_and_missing(plugin, scene, tmp_path):
    result = _run(plugin, scene, str(scene / "heroA"), output_dir=str(tmp_path))
    assert Path(result["paths"][0]).parent == tmp_path
    with pytest.raises(FileNotFoundError):
        _run(plugin, scene, str(scene / "nope"))
    with pytest.raises(ValueError, match="不能为空"):
        plugin.handler({"image_path": ""}, {})


def test_worker_end_to_end(plugin, scene, tmp_path):
    from backend.core.registry import _make_isolated_user_handler

    handler = _make_isolated_user_handler(_PLUGIN_PATH, "sheet_contact")
    result = handler(
        {"image_path": str(scene / "heroA"), "output_dir": str(tmp_path / "e2e")},
        {},
    )
    assert result["ok"] is True, result.get("error")
    assert Path(result["paths"][0]).is_file()
