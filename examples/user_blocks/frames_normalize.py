"""序列帧体型归一（frames_normalize）— Nexuz 用户自定义积木。

跨帧统一体型、帧内不变形：以"锚点内容"为体型基准（攻击/单挑序列默认取
第 1 帧正常站姿，即对峙时显示的姿态），每序列取单一缩放系数
s = 基准锚高 / 锚内容高，整帧 LANCZOS 等比缩放后带位移贴入基准画布
（锚帧底边贴画布底 = 脚底基线、锚帧水平中心对齐画布中心），挥砍/举刀帧的
帧间动作位移按原始比例自然保留，不逐帧裁剪。并集宽超出基准宽时画布按需
加宽（合同口径：高度严格一致、宽度 ≥ 基准宽）。越界帧记入 errors 跳过，
不静默裁切。立绘/行走帧的逐帧顶格归一请用 image_scale，勿用本积木。

安装：放入 %LOCALAPPDATA%/Nexuz/user_blocks/ 并在设置中授权，重启后生效。
设计来源：三十六计_Nexuz序列帧体型归一积木设计_v1.0（锚点/缩放/落位公式同构）。
本机可信插件：隔离 worker 禁止网络与子进程、允许文件读写；请仅授权可信来源。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image

SCHEMA = {
    "type": "frames_normalize",
    "label": "序列帧体型归一",
    "category": "识别类",
    "done_log": "已归一{{count}}帧：{{first_path}}",
    "description": "以锚点帧内容为体型基准，整帧等比缩放+位移贴入基准画布：跨帧统一体型、"
    "帧内不变形、帧间动作位移保留；并集宽超基准宽时画布按需加宽。"
    "本机可信插件：隔离 worker 禁止网络与子进程、允许文件读写。",
    "inputs": [
        {
            "name": "image_path",
            "type": "string",
            "label": "序列帧文件夹",
            "default": "",
            "placeholder": "每行一个文件夹（一个文件夹=一个英雄序列，取按名排序的 png）",
            "ui": "textarea",
            "bindable": True,
            "required": True,
        },
        {
            "name": "reference_folder",
            "type": "string",
            "label": "参照序列",
            "default": "",
            "placeholder": "留空=各序列自身为基准（s=1 仅位置归一）；填写后基准画布与基准锚高取自该序列",
            "ui": "file_or_dir",
            "bindable": True,
        },
        {
            "name": "anchor_mode",
            "type": "select",
            "label": "体型锚点",
            "options": ["normal_frame", "union", "max_content"],
            "default": "normal_frame",
            "option_labels": {
                "normal_frame": "锚点帧内容高（默认，站姿基准）",
                "union": "全帧并集高",
                "max_content": "全帧最大内容高",
            },
        },
        {
            "name": "anchor_frame",
            "type": "number",
            "label": "锚点帧号",
            "default": 1,
            "placeholder": "1 起；仅 锚点帧 模式生效",
            "show_when": {"anchor_mode": "normal_frame"},
        },
        {
            "name": "target_width",
            "type": "number",
            "label": "基准画布宽",
            "default": 0,
            "placeholder": "0=自动（参照序列或第一个文件夹的现画布宽）",
        },
        {
            "name": "target_height",
            "type": "number",
            "label": "基准画布高",
            "default": 0,
            "placeholder": "0=自动（参照序列或第一个文件夹的现画布高）",
        },
        {
            "name": "output_dir",
            "type": "string",
            "label": "输出目录",
            "default": "",
            "placeholder": "留空=输入旁的 文件夹名_norm/；显式指定且多文件夹时按文件夹分子目录",
            "ui": "file_or_dir",
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "count", "type": "number"},
        {"name": "first_path", "type": "string"},
        {"name": "paths", "type": "array"},
        {"name": "per_file", "type": "array"},
        {"name": "errors", "type": "array"},
    ],
}

# 内容判定：alpha > 16 视为有效像素（与设计文档参照脚本一致）
_ALPHA_THRESHOLD = 16
# 亚像素容差：贴边半像素的抗锯齿边缘不算越界（验收口径 ±1px）
_EDGE_EPS = 0.51
# 画布加宽逐步收敛上限（每步 +1px，实际远小于此）
_MAX_WIDEN_STEPS = 4096


def _split_paths(raw: Any) -> list[Path]:
    """多行/列表 → 去重后的路径列表（兼容绑定上游输出的数组）。"""
    if isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        parts = str(raw or "").replace(";", "\n").splitlines()
    out: list[Path] = []
    seen: set[str] = set()
    for part in parts:
        text = str(part).strip().strip('"').strip("'")
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(Path(text))
    return out


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _content_bbox(im: Image.Image) -> tuple[int, int, int, int] | None:
    """alpha>16 的内容包围盒（右/下开区间，PIL getbbox 风格）；空帧返回 None。"""
    mask = im.getchannel("A").point(lambda v: 255 if v > _ALPHA_THRESHOLD else 0)
    return mask.getbbox()


def _load_sequence(
    folder: Path, errors: list[str], label: str
) -> tuple[list[Path], list[tuple[int, int]], list[tuple[int, int, int, int] | None]] | None:
    """按文件名排序读取序列帧；画布不一致/读图失败时记入 errors 并返回 None。"""
    files = sorted(folder.glob("*.png"))
    if not files:
        errors.append(f"{label}：文件夹内没有 png 序列帧")
        return None
    sizes: list[tuple[int, int]] = []
    boxes: list[tuple[int, int, int, int] | None] = []
    for f in files:
        try:
            with Image.open(f) as im:
                rgba = im.convert("RGBA")
                sizes.append(rgba.size)
                boxes.append(_content_bbox(rgba))
        except OSError as exc:
            errors.append(f"{label}/{f.name}：读取失败（{exc}）")
            return None
    base = sizes[0]
    for f, size in zip(files[1:], sizes[1:]):
        if size != base:
            errors.append(
                f"{label}：各帧画布不一致"
                f"（{files[0].name} {base[0]}x{base[1]}，{f.name} {size[0]}x{size[1]}），"
                f"已跳过整个文件夹"
            )
            return None
    return files, sizes, boxes


def _anchor_box(
    boxes: list[tuple[int, int, int, int] | None],
    mode: str,
    anchor_frame: Any,
    label: str,
    errors: list[str],
) -> tuple[int, int, int, int] | None:
    """按 anchor_mode 选锚点包围盒；无法确定时记入 errors 并返回 None。"""
    if mode == "union":
        solid = [b for b in boxes if b]
        if not solid:
            errors.append(f"{label}：全部帧均无内容，无法确定并集锚点")
            return None
        return (
            min(b[0] for b in solid),
            min(b[1] for b in solid),
            max(b[2] for b in solid),
            max(b[3] for b in solid),
        )
    if mode == "max_content":
        best = None
        for b in boxes:
            if b and (best is None or b[3] - b[1] > best[3] - best[1]):
                best = b
        if best is None:
            errors.append(f"{label}：全部帧均无内容，无法确定最大内容锚点")
            return None
        return best
    try:
        index = int(float(anchor_frame if anchor_frame not in (None, "") else 1)) - 1
    except (TypeError, ValueError):
        index = 0
    if index < 0 or index >= len(boxes):
        errors.append(f"{label}：锚点帧号 {anchor_frame} 越界（共 {len(boxes)} 帧）")
        return None
    box = boxes[index]
    if box is None:
        errors.append(f"{label}：锚点帧（第 {index + 1} 帧）无内容，无法确定体型基准")
        return None
    return box


def _normalize_folder(
    folder: Path,
    *,
    anchor_mode: str,
    anchor_frame: Any,
    base_size: tuple[int, int],
    base_anchor_h: float | None,
    out_dir: Path,
    errors: list[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    """归一单个序列文件夹。返回 (输出路径, 每帧明细)；问题一律记入 errors。"""
    label = folder.name
    seq = _load_sequence(folder, errors, label)
    if seq is None:
        return [], []
    files, sizes, boxes = seq
    canvas_w, canvas_h = sizes[0]

    anchor = _anchor_box(boxes, anchor_mode, anchor_frame, label, errors)
    if anchor is None:
        return [], []
    ax0, ay0, ax1, ay1 = anchor
    anchor_h = ay1 - ay0
    if anchor_h <= 0:
        errors.append(f"{label}：锚点内容高为 0，无法归一")
        return [], []
    # 无参照时各序列自身为基准（s=1，仅做锚点位置归一）
    scale = (base_anchor_h / anchor_h) if base_anchor_h else 1.0

    out_w, out_h = base_size

    # 落位：锚帧底边贴画布底（脚底基线）、锚内容水平中心对齐画布中心。
    # PIL 开区间坐标下 (fx0+fx1+1) ≡ x0+x1、(fy1+1) ≡ y1。
    center = (ax0 + ax1) * scale / 2
    dy = math.floor(out_h - ay1 * scale + 0.5)

    # 纵向守卫：高度绝不妥协，越界帧记入 errors 跳过（不静默裁切）
    kept: list[int] = []
    for i, box in enumerate(boxes):
        if box is None:
            errors.append(
                f"{label}/{files[i].name}：空帧（无 alpha>{_ALPHA_THRESHOLD} 的内容），已跳过"
            )
            continue
        top = dy + box[1] * scale
        bottom = dy + box[3] * scale
        if top < -_EDGE_EPS or bottom > out_h + _EDGE_EPS:
            errors.append(
                f"{label}/{files[i].name}：缩放后内容超出画布高"
                f"（内容 y {top:.1f}~{bottom:.1f}，画布高 {out_h}），已跳过"
            )
            continue
        kept.append(i)
    if not kept:
        return [], []

    # 横向：锚内容中心恒对齐画布中心；并集宽超出基准宽 → 画布按需加宽
    right_ext = max(boxes[i][2] for i in kept) * scale
    left_ext = min(boxes[i][0] for i in kept) * scale
    width = out_w
    dx = 0
    for _ in range(_MAX_WIDEN_STEPS):
        dx = math.floor(width / 2 - center + 0.5)
        if dx + left_ext >= -_EDGE_EPS and dx + right_ext <= width + _EDGE_EPS:
            break
        width += 1
    else:
        errors.append(f"{label}：无法在合理画布宽度内容纳全部帧（并集宽过大）")
        return [], []

    out_dir.mkdir(parents=True, exist_ok=True)
    sw = max(1, math.floor(canvas_w * scale + 0.5))
    sh = max(1, math.floor(canvas_h * scale + 0.5))
    paths: list[str] = []
    details: list[dict[str, Any]] = []
    for i in kept:
        file = files[i]
        try:
            with Image.open(file) as im:
                scaled = im.convert("RGBA").resize((sw, sh), Image.Resampling.LANCZOS)
        except OSError as exc:
            errors.append(f"{label}/{file.name}：读取失败（{exc}）")
            continue
        # 透明基准画布整幅贴入（paste 替换像素含 alpha，不合成，帧内不变形）
        frame_out = Image.new("RGBA", (width, out_h), (0, 0, 0, 0))
        frame_out.paste(scaled, (dx, dy))
        target = out_dir / file.name
        try:
            frame_out.save(target)
        except OSError as exc:
            errors.append(f"{label}/{file.name}：保存失败（{exc}）")
            continue
        paths.append(str(target))
        details.append(
            {
                "folder": label,
                "file": file.name,
                "path": str(target),
                "canvas": [canvas_w, canvas_h],
                "scale": round(scale, 6),
                "dx": dx,
                "dy": dy,
                "anchor_content": [ax1 - ax0, anchor_h],
                "output_canvas": [width, out_h],
            }
        )
    return paths, details


def handler(params, context, **kwargs):
    folders = _split_paths(params.get("image_path"))
    if not folders:
        raise ValueError("序列帧文件夹不能为空（每行一个文件夹路径）")

    errors: list[str] = []
    anchor_mode = str(params.get("anchor_mode") or "normal_frame")
    anchor_frame = params.get("anchor_frame")

    ref_list = _split_paths(params.get("reference_folder"))
    if len(ref_list) > 1:
        raise ValueError("参照序列只能填写一个文件夹")
    reference = ref_list[0] if ref_list else None

    base_anchor_h: float | None = None
    fallback_size: tuple[int, int] | None = None
    if reference is not None:
        if not reference.is_dir():
            raise ValueError(f"参照序列文件夹不存在：{reference}")
        ref_seq = _load_sequence(reference, errors, f"参照·{reference.name}")
        if ref_seq is None:
            raise ValueError(f"参照序列不可用：{errors[-1] if errors else '未知原因'}")
        ref_anchor = _anchor_box(
            ref_seq[2], anchor_mode, anchor_frame, f"参照·{reference.name}", errors
        )
        if ref_anchor is None:
            raise ValueError(f"参照序列锚点不可用：{errors[-1] if errors else '未知原因'}")
        base_anchor_h = float(ref_anchor[3] - ref_anchor[1])
        fallback_size = ref_seq[1][0]

    valid: list[Path] = []
    for folder in folders:
        if not folder.is_dir():
            errors.append(f"{folder}：文件夹不存在，已跳过")
            continue
        valid.append(folder)
    if not valid:
        raise ValueError("没有有效的输入序列帧文件夹" + (f"：{errors[0]}" if errors else ""))

    if fallback_size is None:
        # 无参照：基准画布取第一个文件夹第 1 帧现画布
        first_png = sorted(valid[0].glob("*.png"))
        if not first_png:
            raise ValueError(f"第一个文件夹内没有 png 序列帧：{valid[0]}")
        with Image.open(first_png[0]) as im:
            fallback_size = im.size

    target_w = _to_int(params.get("target_width"))
    target_h = _to_int(params.get("target_height"))
    base_size = (
        target_w if target_w > 0 else fallback_size[0],
        target_h if target_h > 0 else fallback_size[1],
    )

    raw_out = str(params.get("output_dir") or "").strip().strip('"').strip("'")
    out_root = Path(raw_out) if raw_out else None
    multiple = len(valid) > 1

    all_paths: list[str] = []
    all_details: list[dict[str, Any]] = []
    for folder in valid:
        if out_root is not None:
            out_dir = out_root / folder.name if multiple else out_root
        else:
            out_dir = folder.parent / f"{folder.name}_norm"
        paths, details = _normalize_folder(
            folder,
            anchor_mode=anchor_mode,
            anchor_frame=anchor_frame,
            base_size=base_size,
            base_anchor_h=base_anchor_h,
            out_dir=out_dir,
            errors=errors,
        )
        all_paths.extend(paths)
        all_details.extend(details)

    return {
        "ok": not errors,
        "count": len(all_paths),
        "first_path": all_paths[0] if all_paths else "",
        "paths": all_paths,
        "per_file": all_details,
        "errors": errors,
    }
