from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.blocks import image_scale


def _build_image(w=200, h=100) -> np.ndarray:
    """带 Alpha 通道的测试图（BGRA，左半不透明色块、右半透明）。"""
    img = np.zeros((h, w, 4), dtype=np.uint8)
    img[:, : w // 2, :3] = (30, 120, 200)
    img[:, : w // 2, 3] = 255
    return img


def _encode(path, img) -> Path:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    buf.tofile(str(path))
    return path


def _read(path) -> np.ndarray:
    data = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    assert data is not None
    return data


BASE_PARAMS = {
    "output_dir": "",
    "scale_percent": 50,
    "interpolation": "auto",
    "name_suffix": "_scale",
}


def _run(tmp_path, image_path, **overrides):
    params = {
        **BASE_PARAMS,
        "image_path": str(image_path),
        **overrides,
    }
    return image_scale.handler(params, context=None)


def test_downscale_keeps_ratio_and_alpha(tmp_path):
    p = _encode(tmp_path / "hero.png", _build_image())

    result = _run(tmp_path, p, output_dir=str(tmp_path / "out"))

    assert result["count"] == 1
    assert result["sheets"] == 1
    assert Path(result["paths"][0]).name == "hero_scale.png"

    out = _read(result["paths"][0])
    assert out.shape[:2] == (50, 100)  # 200x100 → 等比一半
    assert out[:, :50, 3].max() == 255  # 原不透明区域仍不透明
    assert out[:, 50:, 3].max() == 0  # 原透明区域仍透明
    assert result["per_file"][0]["width"] == 100
    assert result["per_file"][0]["height"] == 50


def test_upscale_and_custom_suffix(tmp_path):
    p = _encode(tmp_path / "hero.png", _build_image())

    result = _run(tmp_path, p, scale_percent=200, name_suffix="_big", interpolation="lanczos")

    out = _read(result["paths"][0])
    assert out.shape[:2] == (200, 400)
    assert Path(result["paths"][0]).name == "hero_big.png"


def test_empty_suffix_keeps_name(tmp_path):
    p = _encode(tmp_path / "hero.png", _build_image())

    result = _run(tmp_path, p, output_dir=str(tmp_path / "out"), name_suffix="")

    assert Path(result["paths"][0]).name == "hero.png"


def test_same_target_as_source_raises(tmp_path):
    p = _encode(tmp_path / "hero.png", _build_image())

    # 后缀为空且输出目录默认为原图旁 → 目标与源图相同，拒绝覆盖
    with pytest.raises(ValueError, match="覆盖"):
        _run(tmp_path, p, name_suffix="")


def test_default_output_next_to_source(tmp_path):
    p = _encode(tmp_path / "hero.png", _build_image())

    result = _run(tmp_path, p, output_dir="")

    assert Path(result["paths"][0]) == tmp_path / "hero_scale.png"
    assert result["output_dir"] == str(tmp_path.resolve())


def test_format_preserved(tmp_path):
    jpg_img = np.full((40, 60, 3), 100, dtype=np.uint8)
    jpg_path = _encode(tmp_path / "photo.jpg", jpg_img)

    jpg_res = _run(tmp_path, jpg_path, output_dir=str(tmp_path / "out"))
    assert Path(jpg_res["paths"][0]).suffix == ".jpg"


def test_unsupported_format_falls_back_or_fails(tmp_path):
    # cv2 解码不了的格式（如 gif 占位文件）：单图直接报解码失败
    fake_gif = tmp_path / "anim.gif"
    fake_gif.write_bytes(b"GIF89a-not-a-real-image")

    with pytest.raises(ValueError, match="解码失败"):
        _run(tmp_path, fake_gif, output_dir=str(tmp_path / "out"))


def test_folder_batch_mode(tmp_path):
    folder = tmp_path / "sheets"
    folder.mkdir()
    for name in ("a.png", "b.png"):
        _encode(folder / name, _build_image())
    # 损坏图片进 errors 且不中断；非图片文件被忽略
    (folder / "notes.txt").write_text("not an image", encoding="utf-8")
    (folder / "bad.png").write_bytes(b"\x89PNG\r\n corrupted")

    result = _run(tmp_path, folder, output_dir="")

    assert result["sheets"] == 3  # a/b/bad 共 3 张图片被扫描
    assert result["count"] == 2
    assert len(result["errors"]) == 1
    assert "bad.png" in result["errors"][0]["image"]
    names = {Path(p).name for p in result["paths"]}
    assert names == {"a_scale.png", "b_scale.png"}


def test_batch_output_to_custom_dir(tmp_path):
    folder = tmp_path / "sheets"
    folder.mkdir()
    _encode(folder / "a.png", _build_image())

    result = _run(tmp_path, folder, output_dir=str(tmp_path / "scaled"))

    assert result["output_dir"] == str((tmp_path / "scaled").resolve())
    assert Path(result["paths"][0]).parent == tmp_path / "scaled"


def test_folder_without_images_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "doc.txt").write_text("hi", encoding="utf-8")
    with pytest.raises(ValueError, match="未找到图片"):
        image_scale.handler({"image_path": str(empty)}, context=None)


def test_invalid_params_raise(tmp_path):
    with pytest.raises(ValueError, match="image_path"):
        image_scale.handler({"image_path": ""}, context=None)
    with pytest.raises(FileNotFoundError):
        image_scale.handler({"image_path": str(tmp_path / "missing.png")}, context=None)

    p = _encode(tmp_path / "hero.png", _build_image())
    with pytest.raises(ValueError, match="超出范围"):
        _run(tmp_path, p, scale_percent=5000)
    with pytest.raises(ValueError, match="无效"):
        _run(tmp_path, p, scale_percent="abc")


def test_target_mode_bottom_align(tmp_path):
    """120x80 素材 → 100x100 画布，脚底居中：100x67，底部贴边。"""
    img = np.full((80, 120, 4), 255, dtype=np.uint8)
    img[:, :, :3] = (30, 120, 200)
    p = _encode(tmp_path / "hero.png", img)

    result = _run(
        tmp_path, p, scale_mode="target", target_width=100, target_height=100
    )

    out = _read(result["paths"][0])
    assert out.shape[:2] == (100, 100)  # 输出尺寸完全一致
    assert result["per_file"][0]["padded"] is True
    # 等比缩放 100x67，脚底贴画布底
    assert result["per_file"][0]["scaled"] == [100, 67]
    assert out[99, 50, 3] > 0  # 底部有内容
    assert out[32, 50, 3] == 0  # 素材上方全透明（67 行内容从 y=33 开始）
    assert out[33, 50, 3] > 0


def test_target_mode_center_align_and_margin(tmp_path):
    """几何居中：素材垂直居中；bottom_margin 把脚底抬高。"""
    img = np.full((80, 120, 4), 255, dtype=np.uint8)
    img[:, :, :3] = (30, 120, 200)
    p = _encode(tmp_path / "hero.png", img)

    center = _run(
        tmp_path, p, scale_mode="target", target_width=100, target_height=100,
        align="center",
    )
    out = _read(center["paths"][0])
    assert out.shape[:2] == (100, 100)
    # 100x67 居中 → 内容占 y=16..82，上下各留 16 行透明
    assert out[15, 50, 3] == 0
    assert out[16, 50, 3] > 0
    assert out[82, 50, 3] > 0
    assert out[83, 50, 3] == 0

    margin = _run(
        tmp_path, p, scale_mode="target", target_width=100, target_height=100,
        bottom_margin=4,
    )
    out = _read(margin["paths"][0])
    assert out.shape[:2] == (100, 100)
    # 可用高度 96 不限制缩放（宽度优先）：仍 100x67，脚底离底边 4px
    assert out[95, 50, 3] > 0  # 内容最后一行 y=95
    assert out[96, 50, 3] == 0  # 底部 4px 透明


def test_target_mode_trims_transparent_border(tmp_path):
    """四周透明留白先裁掉：内容 40x40 撑满 100x100 画布。"""
    img = np.zeros((100, 100, 4), dtype=np.uint8)
    img[:, :, :3] = (30, 120, 200)
    img[30:70, 30:70, 3] = 255  # 有效内容 40x40
    p = _encode(tmp_path / "hero.png", img)

    trim = _run(tmp_path, p, scale_mode="target", target_width=100, target_height=100)
    out = _read(trim["paths"][0])
    assert out.shape[:2] == (100, 100)
    assert out[0, 0, 3] > 0  # 内容撑满画布

    # 不裁剪：按原 100x100 缩放，内容仍只占中间 40x40
    keep = _run(
        tmp_path, p, scale_mode="target", target_width=100, target_height=100,
        trim_transparent="no",
    )
    out = _read(keep["paths"][0])
    assert out[0, 0, 3] == 0  # 留白保留


def test_target_mode_batch_auto_target_from_first_image(tmp_path):
    """批量宽高留空：以排序后第一张图（裁剪后）尺寸为准，输出完全一致。"""
    folder = tmp_path / "heroes"
    folder.mkdir()
    # a.png：内容 80x60（裁剪后 80x60 = 目标尺寸）
    a = np.zeros((100, 100, 4), dtype=np.uint8)
    a[:, :, :3] = (30, 120, 200)
    a[10:70, 10:90, 3] = 255
    _encode(folder / "a.png", a)
    # b.png：内容 120x90
    b = np.zeros((150, 200, 4), dtype=np.uint8)
    b[:, :, :3] = (30, 120, 200)
    b[30:120, 40:160, 3] = 255
    _encode(folder / "b.png", b)

    result = _run(tmp_path, folder, scale_mode="target", target_width="", target_height="")

    assert result["count"] == 2
    sizes = {(Path(p).name, _read(p).shape[:2]) for p in result["paths"]}
    assert sizes == {("a_scale.png", (60, 80)), ("b_scale.png", (60, 80))}


def test_target_mode_single_blank_target_raises(tmp_path):
    p = _encode(tmp_path / "hero.png", _build_image())
    with pytest.raises(ValueError, match="必须.*填写|手动填写"):
        _run(tmp_path, p, scale_mode="target", target_width="", target_height="")
    with pytest.raises(ValueError, match="手动填写"):
        _run(tmp_path, p, scale_mode="target", target_width=100, target_height="")


def test_target_mode_no_alpha_becomes_png(tmp_path):
    """无 alpha 的 jpg 需要补透明边 → 转 PNG 导出保留透明度。"""
    jpg_img = np.full((80, 120, 3), 100, dtype=np.uint8)
    p = _encode(tmp_path / "photo.jpg", jpg_img)

    result = _run(tmp_path, p, scale_mode="target", target_width=100, target_height=100)

    out_path = Path(result["paths"][0])
    assert out_path.suffix == ".png"
    out = _read(out_path)
    assert out.shape[2] == 4
    assert out.shape[:2] == (100, 100)


def test_target_mode_nearest_keeps_pixel_edges(tmp_path):
    """像素风：最近邻缩放后无中间过渡色。"""
    img = np.zeros((40, 40, 4), dtype=np.uint8)
    img[:, :, :3] = (30, 120, 200)
    img[10:30, 10:30, 3] = 255
    p = _encode(tmp_path / "pixel.png", img)

    result = _run(
        tmp_path, p, scale_mode="target", target_width=80, target_height=80,
        interpolation="nearest",
    )
    out = _read(result["paths"][0])
    alphas = np.unique(out[:, :, 3])
    assert set(int(a) for a in alphas) <= {0, 255}  # 无半透明过渡


def test_target_mode_zero_means_blank(tmp_path):
    """界面数字框留空会存 0：0/负数按未填写处理，批量自动取第一张图尺寸。"""
    folder = tmp_path / "heroes"
    folder.mkdir()
    a = np.zeros((100, 100, 4), dtype=np.uint8)
    a[:, :, :3] = (30, 120, 200)
    a[20:80, 20:80, 3] = 255
    _encode(folder / "a.png", a)

    result = _run(
        tmp_path, folder, scale_mode="target", target_width=0, target_height=0
    )
    out = _read(result["paths"][0])
    assert out.shape[:2] == (60, 60)  # 以第一张裁剪后尺寸为基准


def test_schema_registered():
    from backend.core.registry import register_block

    register_block(image_scale.SCHEMA, image_scale.handler)
