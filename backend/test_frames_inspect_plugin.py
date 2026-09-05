"""frames_inspect 用户积木：合同校验判定口径（底边/居中/内容高/空帧/画布/参照）。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

_PLUGIN_PATH = (
    Path(__file__).resolve().parents[1] / "examples" / "user_blocks" / "frames_inspect.py"
)


def _load_plugin():
    spec = importlib.util.spec_from_file_location("frames_inspect_under_test", _PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def plugin():
    return _load_plugin()


def _frame(path: Path, rects: list[tuple[int, int, int, int]], size: tuple[int, int] = (100, 80)) -> None:
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    for x0, y0, x1, y1 in rects:
        draw.rectangle([x0, y0, x1 - 1, y1 - 1], fill=(200, 30, 30, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def _contract_frame(path: Path, size: tuple[int, int] = (100, 80)) -> None:
    """合规帧：内容高 40、底边贴画布底、水平居中。"""
    _frame(path, [(30, 40, 70, 80)], size)


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    root = tmp_path_factory.mktemp("frames_inspect")
    # good：两帧全合规
    _contract_frame(root / "good" / "f1.png")
    _contract_frame(root / "good" / "f2.png")
    # ref：参照序列（同 good 基准）
    _contract_frame(root / "ref" / "r1.png")
    _contract_frame(root / "ref" / "r2.png")
    # bad：四种违规各一帧 + 空帧
    _frame(root / "bad" / "bottom.png", [(30, 35, 70, 77)])   # 底边距 3 > 1
    _frame(root / "bad" / "height.png", [(30, 30, 70, 80)])   # 内容高 50，偏差 10 > 1
    _frame(root / "bad" / "center.png", [(10, 40, 50, 80)])   # 居中偏差 20 > 2
    _frame(root / "bad" / "empty.png", [])                     # 空帧
    # mixed：画布不一致
    _contract_frame(root / "mixed" / "m1.png")
    _contract_frame(root / "mixed" / "m2.png", size=(90, 70))
    return root


def _run(plugin, root: Path, folders: str, **extra):
    params = {
        "image_path": "\n".join(str(root / name) for name in folders.split(",")),
        **extra,
    }
    return plugin.handler(params, {})


def test_contract_pass(plugin, scene):
    result = _run(plugin, scene, "good")
    assert result["ok"] is True, result["errors"]
    assert result["folders"] == 1 and result["frames"] == 2
    detail = result["per_folder"][0]
    assert detail["canvas"] == [100, 80]
    assert detail["content_h_median"] == 40
    assert all(d["ok"] for d in detail["frame_details"])


def test_reference_mode_baseline(plugin, scene):
    """参照模式：基准取自参照序列；合规序列仍全过。"""
    result = _run(plugin, scene, "good,ref".replace(",ref", ""), reference_folder=str(scene / "ref"))
    assert result["ok"] is True, result["errors"]
    result2 = plugin.handler(
        {
            "image_path": str(scene / "good"),
            "reference_folder": str(scene / "ref"),
        },
        {},
    )
    assert result2["ok"] is True, result2["errors"]
    assert result2["per_folder"][0]["content_h_median"] == 40


def test_violations_recorded(plugin, scene):
    result = _run(plugin, scene, "bad")
    assert result["ok"] is False
    joined = "\n".join(result["errors"])
    assert "bottom.png" in joined and "底边距" in joined
    assert "height.png" in joined and "内容高" in joined
    assert "center.png" in joined and "居中偏差" in joined
    assert "empty.png" in joined and "空帧" in joined
    # 合规帧不误伤：per_folder 明细里各违规帧 ok=False
    detail = result["per_folder"][0]
    by_file = {d["file"]: d for d in detail["frame_details"]}
    assert by_file["empty.png"]["ok"] is False
    assert by_file["bottom.png"]["bottom_margin"] == 3


def test_canvas_mismatch(plugin, scene):
    result = _run(plugin, scene, "mixed")
    assert result["ok"] is False
    assert any("m2.png" in e and "画布" in e for e in result["errors"])
    # 期望画布参数可覆盖：显式给 90x70 后画布违规项落到 m1；m2 不再报画布项
    # （其余合同项仍按其内容实测）
    result2 = _run(plugin, scene, "mixed", canvas_w=90, canvas_h=70)
    joined = "\n".join(result2["errors"])
    assert "m1.png" in joined and "画布" in joined
    m2_errors = [e for e in result2["errors"] if "m2.png" in e]
    assert m2_errors and all("画布" not in e for e in m2_errors)


def test_missing_folder_recorded(plugin, scene):
    result = _run(plugin, scene, "good,nope")
    assert any("不存在" in e for e in result["errors"])
    assert result["frames"] == 2 and result["folders"] == 1


def test_empty_input_raises(plugin):
    with pytest.raises(ValueError, match="不能为空"):
        plugin.handler({"image_path": ""}, {})


def test_worker_end_to_end(plugin, scene):
    from backend.core.registry import _make_isolated_user_handler

    handler = _make_isolated_user_handler(_PLUGIN_PATH, "frames_inspect")
    result = handler({"image_path": str(scene / "good")}, {})
    assert result["ok"] is True, result.get("error")
    assert result["frames"] == 2
