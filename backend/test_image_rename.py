from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from backend.blocks import image_rename


def _make_png(path: Path, size: tuple[int, int] = (8, 6), marker: int = 30) -> Path:
    """生成真实 PNG（重命名需读取宽高），marker 区分文件内容。"""
    img = np.full((size[1], size[0], 3), marker, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    buf.tofile(str(path))
    return path


def _names(folder: Path) -> set[str]:
    return {p.name for p in folder.iterdir()}


BASE_PARAMS = {
    "image_path": "",
    "output_dir": "",
    "name_template": "",
    "recognize_mode": "none",
    "ocr_line": "first",
    "ai_prompt": "",
    "timeout_s": 60,
    "text_max_len": 20,
    "start_index": 1,
    "index_digits": 2,
    "conflict_mode": "rename",
    "dry_run": "false",
}


def _run(tmp_path, folder: Path, **overrides):
    params = {
        **BASE_PARAMS,
        "image_path": str(folder),
        **overrides,
    }
    return image_rename.handler(params, context=None)


def _item(result, old_name: str) -> dict:
    for it in result["items"]:
        if Path(it["old"]).name == old_name:
            return it
    raise AssertionError(f"items 中找不到 {old_name}")


def test_template_with_index(tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png")
    _make_png(folder / "b.png")

    result = _run(tmp_path, folder, name_template="game_{n}")

    assert result["count"] == 2
    assert _names(folder) == {"game_01.png", "game_02.png"}
    assert Path(result["paths"][0]).name == "game_01.png"


def test_template_name_width_height_and_start(tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png", size=(8, 6))  # PIL size → width=8 height=6
    _make_png(folder / "b.png", size=(8, 6))

    result = _run(
        tmp_path,
        folder,
        name_template="{width}x{height}_{name}_{n}",
        start_index=5,
        index_digits=0,
    )

    assert _names(folder) == {"8x6_a_5.png", "8x6_b_6.png"}


def test_template_manual_format_spec(tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png")

    result = _run(tmp_path, folder, name_template="n{n:03d}")

    assert _names(folder) == {"n001.png"}


def test_parent_and_date_placeholders(tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png")

    result = _run(tmp_path, folder, name_template="{parent}_{date}")

    import re

    stem = next(iter(_names(folder)))
    assert stem.startswith("imgs_")
    assert re.fullmatch(r"imgs_\d{8}\.png", stem)


def test_extension_preserved(tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    img = np.zeros((4, 4, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    buf.tofile(str(folder / "a.jpg"))

    result = _run(tmp_path, folder, name_template="x_{n}")

    assert _names(folder) == {"x_01.jpg"}


def test_conflict_auto_suffix(tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png", marker=1)
    _make_png(folder / "c.png", marker=2)  # 目标名 c 已被占用

    result = _run(tmp_path, folder, name_template="c")

    assert result["count"] == 1
    assert result["unchanged"] == 1
    assert _names(folder) == {"c.png", "c_2.png"}
    # 占用者（原 c.png）保持不动，a.png 让位为 c_2.png
    assert _item(result, "a.png")["new"].endswith("c_2.png")
    assert _item(result, "c.png")["status"] == "unchanged"


def test_conflict_skip(tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png", marker=1)
    _make_png(folder / "c.png", marker=2)

    result = _run(tmp_path, folder, name_template="c", conflict_mode="skip")

    assert result["skipped"] == 1
    assert result["count"] == 0
    assert _item(result, "a.png")["status"] == "skipped"
    assert (folder / "a.png").exists()  # 原文件未动


def test_conflict_overwrite(tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png", marker=1)
    _make_png(folder / "c.png", marker=2)

    result = _run(tmp_path, folder, name_template="c", conflict_mode="overwrite")

    assert result["count"] == 1
    assert _names(folder) == {"c.png"}
    # c.png 内容被 a.png 替换
    data = cv2.imdecode(
        np.fromfile(str(folder / "c.png"), dtype=np.uint8), cv2.IMREAD_COLOR
    )
    assert data.min() == 1 and data.max() == 1


def test_unchanged_noop(tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png")
    _make_png(folder / "b.png")

    result = _run(tmp_path, folder, name_template="{name}")

    assert result["count"] == 0
    assert result["unchanged"] == 2
    assert _names(folder) == {"a.png", "b.png"}


def test_dry_run_touches_nothing(tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png")
    _make_png(folder / "b.png")

    result = _run(tmp_path, folder, name_template="game_{n}", dry_run="true")

    assert result["count"] == 0
    assert _names(folder) == {"a.png", "b.png"}  # 磁盘未动
    statuses = {it["status"] for it in result["items"]}
    assert statuses == {"preview"}
    assert "a.png → game_01.png" in result["preview"]


def test_copy_mode_keeps_originals(tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png", marker=1)
    _make_png(folder / "b.png", marker=2)
    dest = tmp_path / "out"
    dest.mkdir()
    _make_png(dest / "a_new.png", marker=9)  # 目标目录已有同名 → 后缀

    result = _run(
        tmp_path,
        folder,
        name_template="{name}_new",
        output_dir=str(dest),
    )

    assert result["count"] == 2
    assert _names(folder) == {"a.png", "b.png"}  # 原文件保留
    assert _names(dest) == {"a_new.png", "a_new_2.png", "b_new.png"}
    assert Path(result["output_dir"]) == dest.resolve()


def test_output_dir_same_as_source_falls_back_to_rename(tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png")

    result = _run(tmp_path, folder, name_template="x_{n}", output_dir=str(folder))

    assert _names(folder) == {"x_01.png"}


def test_illegal_chars_sanitized(tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png")

    _run(tmp_path, folder, name_template="a:b*c?d")

    assert _names(folder) == {"a_b_c_d.png"}


def test_reserved_device_name_prefixed(tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png")

    _run(tmp_path, folder, name_template="CON")

    assert _names(folder) == {"_CON.png"}


def test_unknown_placeholder_raises(tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png")

    with pytest.raises(ValueError, match="不支持的占位符"):
        _run(tmp_path, folder, name_template="{foo}_{n}")


def test_text_placeholder_requires_ocr(tmp_path):
    with pytest.raises(ValueError, match="OCR"):
        _run(tmp_path, tmp_path, name_template="{text}")


def test_ai_placeholder_requires_ai_mode(tmp_path):
    with pytest.raises(ValueError, match="AI"):
        _run(tmp_path, tmp_path, name_template="{ai}")


def test_bad_format_spec_raises(tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png")

    with pytest.raises(ValueError, match="格式无效"):
        _run(tmp_path, folder, name_template="{name:03d}")


def test_unclosed_brace_raises(tmp_path):
    with pytest.raises(ValueError, match="花括号"):
        _run(tmp_path, tmp_path, name_template="game_{n")


def test_empty_template_raises(tmp_path):
    with pytest.raises(ValueError, match="命名规则"):
        _run(tmp_path, tmp_path, name_template="")


def test_ocr_naming_modes(tmp_path, monkeypatch):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png")
    _make_png(folder / "b.png")

    calls: list[tuple[str, str]] = []

    def fake_ocr(path: Path, pick: str) -> str:
        calls.append((path.name, pick))
        if path.name == "a.png":
            return "第 一 行"  # 空格折叠为下划线
        return ""  # b 识别为空 → 回退原名

    monkeypatch.setattr(image_rename, "_ocr_pick_text", fake_ocr)

    result = _run(tmp_path, folder, name_template="{text}", recognize_mode="ocr")

    assert result["count"] == 1
    assert result["unchanged"] == 1
    assert _names(folder) == {"第_一_行.png", "b.png"}
    assert _item(result, "b.png")["recognized"] == "b"
    assert calls and all(pick == "first" for _, pick in calls)


def test_ocr_join_mode(tmp_path, monkeypatch):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png")

    monkeypatch.setattr(
        image_rename, "_ocr_pick_text", lambda path, pick: "标题\n副标题"
    )

    _run(
        tmp_path,
        folder,
        name_template="{text}",
        recognize_mode="ocr",
        ocr_line="join",
    )

    assert _names(folder) == {"标题_副标题.png"}


def test_text_max_len_truncates(tmp_path, monkeypatch):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png")

    monkeypatch.setattr(image_rename, "_ocr_pick_text", lambda path, pick: "一个特别特别长的识别结果文本")

    _run(tmp_path, folder, name_template="{text}", recognize_mode="ocr", text_max_len=5)

    assert _names(folder) == {"一个特别特.png"}


def test_ai_naming_success_and_failure(tmp_path, monkeypatch):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png")
    _make_png(folder / "b.png")

    monkeypatch.setattr(
        image_rename,
        "get_ai_config",
        lambda: SimpleNamespace(base_url="http://x/v1", api_key="k", model="m"),
    )

    def fake_ai(path: Path, ai_cfg, prompt: str, timeout_s: float) -> str:
        if path.name == "a.png":
            assert ai_cfg["model"] == "m"
            return "「宝剑图标」"
        raise ValueError("HTTP 401 无效密钥")

    monkeypatch.setattr(image_rename, "_ai_name", fake_ai)

    result = _run(tmp_path, folder, name_template="{ai}", recognize_mode="ai")

    assert result["count"] == 1
    assert result["failed"] == 1
    assert _names(folder) == {"宝剑图标.png", "b.png"}  # 失败的保持原名
    assert any("401" in e["error"] for e in result["errors"])


def test_ai_unconfigured_raises(tmp_path, monkeypatch):
    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_png(folder / "a.png")

    monkeypatch.setattr(
        image_rename,
        "get_ai_config",
        lambda: SimpleNamespace(base_url="", api_key="", model=""),
    )

    with pytest.raises(ValueError, match="未配置聊天模型"):
        _run(tmp_path, folder, name_template="{ai}", recognize_mode="ai")


def test_single_file_mode(tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    p = _make_png(folder / "only.png")

    result = _run(tmp_path, folder, image_path=str(p), name_template="solo_{n}")

    assert result["count"] == 1
    assert _names(folder) == {"solo_01.png"}


def test_folder_without_images_raises(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    (folder / "doc.txt").write_text("hi", encoding="utf-8")

    with pytest.raises(ValueError, match="未找到图片"):
        _run(tmp_path, folder, name_template="{name}")


def test_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        image_rename.handler(
            {"image_path": str(tmp_path / "missing"), "name_template": "{name}"},
            context=None,
        )


def test_schema_registered():
    from backend.core.registry import register_block

    register_block(image_rename.SCHEMA, image_rename.handler)
