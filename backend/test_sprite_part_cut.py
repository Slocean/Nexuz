"""sprite_part_cut：区域切件、同画布回贴、排除区补全、manifest 与参数解析。"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.blocks import sprite_part_cut as spc


def _write_png(path: Path, data: np.ndarray) -> Path:
    ok, buf = cv2.imencode(".png", data)
    assert ok
    buf.tofile(str(path))
    return path


def _read_rgba(path) -> np.ndarray:
    data = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    assert data is not None and data.ndim == 3 and data.shape[2] == 4
    return data


@pytest.fixture()
def puppet_src(tmp_path) -> tuple[Path, np.ndarray]:
    """100x100 透明底立绘（BGR）：

    - 躯干 [10:90, 10:50] 绿袍 (20,180,20)
    - 手臂 [30:70, 40:80] 红色 (40,40,220)，右半压在躯干上
    - 手臂上的蓝色细节 [35:45, 60:70] (200,100,0)
    - 其余全透明（alpha=0）
    """
    bgra = np.zeros((100, 100, 4), dtype=np.uint8)
    bgra[10:90, 10:50] = (20, 180, 20, 255)
    bgra[30:70, 40:80] = (40, 40, 220, 255)
    bgra[35:45, 60:70] = (200, 100, 0, 255)
    return _write_png(tmp_path / "hero.png", bgra), bgra


PARTS_JSON = (
    '[{"name":"torso","rect":[0,0,100,100],"exclude":["arm_weapon"],"fill":true},'
    '{"name":"arm_weapon","rect":[40,20,90,70]}]'
)


def _run(tmp_path, src, **overrides):
    params = {
        "image_path": str(src),
        "output_dir": str(tmp_path / "puppet"),
        "parts": PARTS_JSON,
        "pivot": "50,45",
        "pivot_label": "肩关节",
        **overrides,
    }
    return spc.handler(params, context=None)


def test_parts_same_canvas_and_layering(tmp_path, puppet_src):
    """核心不变量：两件画布同源图、叠放还原原图、手臂区从躯干层挖空。"""
    src, data = puppet_src
    result = _run(tmp_path, src)

    assert result["count"] == 2
    assert result["canvas_w"] == 100 and result["canvas_h"] == 100
    torso = _read_rgba(result["paths"]["torso"])
    arm = _read_rgba(result["paths"]["arm_weapon"])
    assert torso.shape == data.shape and arm.shape == data.shape

    # 手臂矩形内：手臂/细节像素（1600）只属于手臂层
    assert (arm[30:70, 40:80, 3] == 255).sum() == 1600
    # 躯干层：矩形内的背景 [y20:30, x50:80] 挖空；袍子遮挡区补回绿色
    assert (torso[20:30, 50:80, 3] == 0).all()
    assert (torso[30:70, 40:50, 3] == 255).all()
    assert (torso[30:70, 40:50, 0] == 20).all() and (torso[30:70, 40:50, 1] == 180).all()

    # 同画布回贴：手臂层叠到躯干层上应还原原图（不透明像素逐像素一致）
    merged = torso.copy()
    m = arm[:, :, 3] > 0
    merged[m] = arm[m]
    opaque = data[:, :, 3] > 0
    assert (merged[opaque] == data[opaque]).all()


def test_fill_restores_hidden_pixels_with_dominant_color(tmp_path, puppet_src):
    """exclude+fill：被手臂遮住/盖住的躯干像素用躯干保留区主色（绿）补回。"""
    src, _data = puppet_src
    result = _run(tmp_path, src)

    torso = _read_rgba(result["paths"]["torso"])
    # 手臂矩形覆盖的躯干区域 [y30:70, x40:50] 补回绿袍
    filled = torso[30:70, 40:50]
    assert (filled[:, :, 3] == 255).all()
    assert (filled[:, :, 0] == 20).all() and (filled[:, :, 1] == 180).all()

    # 矩形内的透明背景不参与补全
    assert (torso[20:30, 50:80, 3] == 0).all()

    # 补全像素数 = 矩形内全部不透明像素（躯干 500 + 手臂出体部分 1200）
    per_part = {p["name"]: p for p in result["per_part"]}
    assert per_part["torso"]["filled_pixels"] == 1700
    assert per_part["torso"]["fill"] is True

    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["canvas"] == {"width": 100, "height": 100}
    assert manifest["pivot"]["x"] == 50 and manifest["pivot"]["y"] == 45
    assert manifest["pivot"]["label"] == "肩关节"
    assert manifest["pivot"]["part"] == "arm_weapon"
    assert [layer["file"] for layer in manifest["layers"]] == ["torso.png", "arm_weapon.png"]
    assert [layer["z"] for layer in manifest["layers"]] == [0, 1]


def test_fill_explicit_color_and_source_transparency(tmp_path, puppet_src):
    """显式 fill_color 生效；源图透明像素不被补全。"""
    src, bgra = puppet_src
    # 在袍子上挖一个透明孔（手臂矩形之外）
    bgra[60:70, 20:30, 3] = 0
    src2 = _write_png(Path(src).with_name("hero2.png"), bgra)

    result = _run(
        tmp_path,
        src2,
        parts='[{"name":"torso","rect":[0,0,100,100],"exclude":["arm_weapon"],"fill":"#FF8800"},'
        '{"name":"arm_weapon","rect":[40,20,90,70]}]',
    )
    torso = _read_rgba(result["paths"]["torso"])
    filled = torso[30:70, 40:50]
    assert (filled[:, :, 0] == 0).all() and (filled[:, :, 1] == 136).all() and (filled[:, :, 2] == 255).all()
    # 源图透明处保持透明：袍子上的孔、矩形内背景
    assert (torso[60:70, 20:30, 3] == 0).all()
    assert (torso[20:30, 50:80, 3] == 0).all()


def test_multiline_parts_without_pivot(tmp_path, puppet_src):
    """行格式解析（无 exclude/fill 语义）；pivot 留空不写入 manifest。"""
    src, _data = puppet_src
    result = _run(
        tmp_path,
        src,
        parts="torso,0,0,100,100\narm_weapon,40,20,90,70",
        pivot="",
        pivot_label="",
    )
    assert result["count"] == 2
    assert result["pivot_x"] is None and result["pivot_y"] is None
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["pivot"] is None
    assert manifest["layers"][0]["z"] == 0 and manifest["layers"][1]["z"] == 1
    # 无 exclude：躯干层保留全部源像素（含手臂），手臂层自带重叠区
    torso = _read_rgba(result["paths"]["torso"])
    assert (torso[30:70, 40:50, 3] == 255).all()


def test_json_string_parts_and_defaults(tmp_path, puppet_src):
    """MCP agent 可能传 JSON 字符串形式的 parts；fill 默认随 exclude 开启。"""
    src, _data = puppet_src
    result = _run(
        tmp_path,
        src,
        parts=json.dumps(
            [
                {"name": "torso", "rect": {"x": 0, "y": 0, "w": 100, "h": 100}, "exclude": ["arm_weapon"]},
                {"name": "arm_weapon", "rect": [40, 20, 90, 70]},
            ]
        ),
    )
    per_part = {p["name"]: p for p in result["per_part"]}
    assert per_part["torso"]["fill"] is True
    assert result["count"] == 2


def test_parse_parts_errors():
    with pytest.raises(ValueError, match="重复"):
        spc._parse_parts("a,0,0,10,10\na,5,5,15,15")
    with pytest.raises(ValueError, match="格式"):
        spc._parse_parts("a,0,0,10,10\nb,5,5,15,15,extra")
    with pytest.raises(ValueError, match="不存在"):
        spc._parse_parts([{"name": "a", "rect": [0, 0, 10, 10], "exclude": ["nope"]}])
    with pytest.raises(ValueError, match="自己"):
        spc._parse_parts([{"name": "a", "rect": [0, 0, 10, 10], "exclude": ["a"]}])
    with pytest.raises(ValueError, match="name"):
        spc._parse_parts([{"rect": [0, 0, 10, 10]}])
    with pytest.raises(ValueError, match="rect"):
        spc._parse_parts([{"name": "a"}])
    assert spc._parse_parts("# 注释行\nb,0,0,10,10")[0]["name"] == "b"


def test_feather_softens_only_kept_edges(tmp_path, puppet_src):
    """羽化软化保留区轮廓；补全区与背景保持各自硬 alpha。"""
    src, _data = puppet_src
    result = _run(
        tmp_path,
        src,
        parts='[{"name":"torso","rect":[0,0,100,100],"exclude":["arm_weapon"],"fill":true,"feather":2},'
        '{"name":"arm_weapon","rect":[40,20,90,70],"feather":2}]',
    )
    torso = _read_rgba(result["paths"]["torso"])
    # 补全区（四周均为实心：上接袍子/左侧袍子/下方袍子…）保持 255
    assert (torso[30:70, 40:50, 3] == 255).all()
    # 矩形内背景不参与补全，羽化不会把它点亮
    assert (torso[20:30, 50:80, 3] == 0).all()
    # 画布最外圈是纯背景
    assert (torso[0:3, :, 3] == 0).all()


def test_rect_outside_canvas_rejected(tmp_path, puppet_src):
    src, _data = puppet_src
    with pytest.raises(ValueError, match="arm"):
        _run(tmp_path, src, parts="torso,0,0,100,100\narm,150,150,200,200")


def test_unknown_image(tmp_path):
    with pytest.raises(FileNotFoundError):
        spc.handler(
            {
                "image_path": str(tmp_path / "nope.png"),
                "parts": "a,0,0,10,10",
            },
            context=None,
        )
