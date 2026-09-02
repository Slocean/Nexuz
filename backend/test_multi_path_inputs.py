"""多路径输入（多选文件/多行路径/绑定路径列表）共通逻辑与积木行为测试。

覆盖：
- _helpers.split_input_paths：多行字符串、绑定上游 list、去重、引号剥离
- _helpers.expand_image_sources：文件保留、文件夹扫描一层、去重保序、全空报错
- transparent_cut / image_scale / image_rename 的多来源批量（_run_multi 分支）
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from backend.blocks import image_rename, image_scale, transparent_cut
from backend.blocks._helpers import expand_image_sources, split_input_paths

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def _write_png(path, size=(24, 24)) -> None:
    img = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    img[4:20, 4:20, :3] = (80, 160, 240)
    img[4:20, 4:20, 3] = 255
    ok, buf = cv2.imencode(".png", img)
    assert ok
    buf.tofile(str(path))


# --- split_input_paths ------------------------------------------------------


def test_split_input_paths_multiline_and_list():
    multiline = "C:\\a\\1.png\n\nC:\\a\\2.png \n"
    assert [str(p) for p in split_input_paths(multiline)] == [r"C:\a\1.png", r"C:\a\2.png"]
    # 绑定上游输出：直接给 list
    assert [str(p) for p in split_input_paths(["C:\\a\\1.png", "C:\\a\\2.png"])] == [
        r"C:\a\1.png",
        r"C:\a\2.png",
    ]


def test_split_input_paths_dedupe_and_quotes():
    value = '"C:\\a\\1.png"\n c:\\A\\1.PNG \nC:\\a\\2.png'
    assert [str(p) for p in split_input_paths(value)] == [r"C:\a\1.png", r"C:\a\2.png"]
    assert split_input_paths("") == []
    assert split_input_paths(None) == []


# --- expand_image_sources ---------------------------------------------------


def test_expand_image_sources_files_dirs_dedupe(tmp_path):
    d1 = tmp_path / "d1"
    d2 = tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()
    for name in ("b.png", "a.png"):
        _write_png(d1 / name)
    (d1 / "note.txt").write_text("x", encoding="utf-8")
    _write_png(d2 / "c.jpg")
    (d2 / "note.txt").write_text("x", encoding="utf-8")
    single = tmp_path / "solo.png"
    _write_png(single)

    files = expand_image_sources([single, d1, d2, single, d1], IMAGE_EXTS)
    names = [f.name for f in files]
    # solo.png 最前（来源顺序，重复传入只保留一次），d1 扫描排序 a/b，
    # c.jpg 来自 d2；note.txt 按扩展名过滤
    assert names == ["solo.png", "a.png", "b.png", "c.jpg"]


def test_expand_image_sources_all_empty_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="未找到"):
        expand_image_sources([empty], IMAGE_EXTS)


# --- transparent_cut 多来源 -------------------------------------------------


def _cut_params(src_value, tmp_path) -> dict:
    return {
        "image_path": src_value,
        "cut_mode": "components",
        "alpha_threshold": 8,
        "shape_mode": "rect",
    }


def test_transparent_cut_multi_files(tmp_path):
    f1 = tmp_path / "one.png"
    f2 = tmp_path / "two.png"
    _write_png(f1)
    _write_png(f2)
    res = transparent_cut.handler(
        _cut_params(f"{f1}\n{f2}", tmp_path), context=None
    )
    assert res["sheets"] == 2
    assert res["count"] == 2
    assert res["skipped"] == 0
    assert res["errors"] == []
    assert len(res["paths"]) == 2


def test_transparent_cut_multi_mixed_file_and_dir(tmp_path):
    folder = tmp_path / "batch"
    folder.mkdir()
    _write_png(folder / "b.png")
    _write_png(folder / "a.png")
    solo = tmp_path / "solo.webp"
    _write_png(solo)
    res = transparent_cut.handler(
        _cut_params(f"{solo}\n{folder}", tmp_path), context=None
    )
    assert res["sheets"] == 3


def test_transparent_cut_multi_list_binding(tmp_path):
    f1 = tmp_path / "one.png"
    f2 = tmp_path / "one.png"  # 同路径重复 → 去重后单文件
    _write_png(f1)
    res = transparent_cut.handler(
        _cut_params([str(f1), str(f2)], tmp_path), context=None
    )
    assert res["sheets"] == 1


def test_transparent_cut_multi_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        transparent_cut.handler(
            _cut_params(f"{tmp_path / 'nope.png'}", tmp_path), context=None
        )


# --- image_scale 多来源 -----------------------------------------------------


def test_image_scale_multi_files(tmp_path):
    f1 = tmp_path / "one.png"
    f2 = tmp_path / "two.png"
    _write_png(f1)
    _write_png(f2)
    res = image_scale.handler(
        {
            "image_path": f"{f1}\n{f2}",
            "scale_mode": "percent",
            "scale_percent": 50,
            "name_suffix": "_scale",
        },
        context=None,
    )
    assert res["sheets"] == 2
    assert res["count"] == 2


# --- image_rename 多来源 ----------------------------------------------------


def test_image_rename_multi_sources_copy(tmp_path):
    d1 = tmp_path / "d1"
    d2 = tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()
    _write_png(d1 / "b.png")
    _write_png(d1 / "a.png")
    _write_png(d2 / "c.png")
    out = tmp_path / "out"

    res = image_rename.handler(
        {
            "image_path": f"{d1 / 'b.png'}\n{d2}\n{d1 / 'a.png'}",
            "name_template": "img_{n}",
            "recognize_mode": "none",
            "output_dir": str(out),
        },
        context=None,
    )
    # b.png（多选文件）→ d2 文件夹扫描 c.png → a.png（多选文件）；不与来源重复合并
    # {n} 默认按 digits=2 补零
    names = [item["name"] for item in res["items"]]
    assert names == ["img_01", "img_02", "img_03"]
    assert res["count"] == 3
    assert all(item["status"] == "renamed" for item in res["items"])
    assert out.joinpath("img_01.png").is_file()
    assert out.joinpath("img_02.png").is_file()
    assert out.joinpath("img_03.png").is_file()
