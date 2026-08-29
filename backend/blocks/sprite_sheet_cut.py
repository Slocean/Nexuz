"""多宫格精灵图智能分割与去底切图。

流水线：宫格划分（手动行列 / 投影自动识别）→ 外部连通域去底（仅清除
接触单元格边界的背景色连通域，保护素材内部同色像素）→ 闭运算粘连近邻
部件 → 面积阈值过滤标号/水印/噪点 → 紧贴包围盒裁切 → 批量导出透明 PNG。
"""

from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np

SCHEMA = {
    "type": "sprite_sheet_cut",
    "label": "精灵图智能切图",
    "category": "识别类",
    "inputs": [
        {
            "name": "image_path",
            "type": "string",
            "label": "精灵图路径/文件夹",
            "default": "",
            "placeholder": "图片文件，或包含多张精灵图的文件夹（批量）",
            "ui": "file_or_dir",
            "bindable": True,
        },
        {
            "name": "output_dir",
            "type": "string",
            "label": "输出目录",
            "default": "",
            "placeholder": "留空则输出到输入路径所在目录",
            "ui": "file_or_dir",
        },
        {
            "name": "grid_mode",
            "type": "select",
            "label": "宫格划分",
            "options": ["manual", "auto"],
            "default": "manual",
            "option_labels": {
                "manual": "手动行列",
                "auto": "自动识别（投影法）",
            },
        },
        {
            "name": "rows",
            "type": "number",
            "label": "行数",
            "default": 3,
            "show_when": {"grid_mode": "manual"},
        },
        {
            "name": "cols",
            "type": "number",
            "label": "列数",
            "default": 3,
            "show_when": {"grid_mode": "manual"},
        },
        {
            "name": "inset_margin",
            "type": "number",
            "label": "单元格内缩(像素)",
            "default": 2,
            "placeholder": "避开格子边缘的外框线",
            "show_when": {"grid_mode": "manual"},
        },
        {
            "name": "bg_color",
            "type": "string",
            "label": "背景色",
            "default": "",
            "placeholder": "留空自动取四角；支持 #RRGGBB 或 R,G,B",
        },
        {
            "name": "tolerance",
            "type": "number",
            "label": "颜色容差",
            "default": 15,
            "placeholder": "各通道最大差值 0~255",
        },
        {
            "name": "close_radius",
            "type": "number",
            "label": "部件合并半径",
            "default": 2,
            "placeholder": "粘连贴身碎部件（光效等），0=关闭",
        },
        {
            "name": "min_area",
            "type": "number",
            "label": "最小保留面积",
            "default": 0,
            "placeholder": "低于该面积视为标号/噪点，0=自动",
        },
        {
            "name": "padding",
            "type": "number",
            "label": "裁切外扩(像素)",
            "default": 0,
        },
        {
            "name": "feather",
            "type": "number",
            "label": "边缘羽化(像素)",
            "default": 1,
            "placeholder": "软化抠图边缘，0=硬边",
        },
    ],
    "outputs": [
        {"name": "output_dir", "type": "string"},
        {"name": "count", "type": "number"},
        {"name": "skipped", "type": "number"},
        {"name": "rows", "type": "number"},
        {"name": "cols", "type": "number"},
        {"name": "paths", "type": "object"},
        {"name": "sheets", "type": "number"},
        {"name": "per_file", "type": "object"},
        {"name": "errors", "type": "object"},
    ],
}

# 批量模式下扫描的图片扩展名
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def _parse_bg_color(text: str) -> tuple[int, int, int] | None:
    """解析用户输入的背景色（按 RGB 理解），返回 BGR 元组；空返回 None 表示自动。"""
    t = str(text or "").strip()
    if not t:
        return None
    if t.startswith("#"):
        hexval = t[1:]
        if len(hexval) != 6:
            raise ValueError(f"背景色格式应为 #RRGGBB，收到: {text}")
        r, g, b = (int(hexval[i : i + 2], 16) for i in (0, 2, 4))
        return (b, g, r)
    parts = re.split(r"[,\s]+", t)
    if len(parts) != 3:
        raise ValueError(f"背景色格式应为 #RRGGBB 或 R,G,B，收到: {text}")
    r, g, b = (int(p) for p in parts)
    for v in (r, g, b):
        if not 0 <= v <= 255:
            raise ValueError(f"背景色分量超出 0~255: {text}")
    return (b, g, r)


def _auto_bg_color(bgr: np.ndarray) -> tuple[int, int, int]:
    """取四角 2x2 区域像素的中位数作为背景色（BGR）。"""
    h, w = bgr.shape[:2]
    m = min(2, h, w)
    corners = np.concatenate(
        [
            bgr[:m, :m].reshape(-1, 3),
            bgr[:m, -m:].reshape(-1, 3),
            bgr[-m:, :m].reshape(-1, 3),
            bgr[-m:, -m:].reshape(-1, 3),
        ]
    )
    med = np.median(corners, axis=0)
    return tuple(int(v) for v in med)


def _contiguous_bands(has: np.ndarray) -> list[tuple[int, int]]:
    """布尔序列中连续 True 段列表，元素为 [start, end) 区间。"""
    bands: list[tuple[int, int]] = []
    start = None
    for i, flag in enumerate(has):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            bands.append((start, i))
            start = None
    if start is not None:
        bands.append((start, len(has)))
    return bands


def _detect_grid_cells(
    fg_any: np.ndarray, close_radius: int = 0
) -> tuple[list[tuple[int, int, int, int]], int, int]:
    """投影法自动识别单元格：先按行投影分行带，再在行带内按列投影分格。

    投影前先按 close_radius 闭运算粘连近邻部件，避免多部件素材
    （主体 + 贴身光效）之间的细小空隙被误判为单元格分界。

    返回 (单元格列表 [x1,y1,x2,y2)，行带数, 最大列带数)。
    """
    if close_radius > 0:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * close_radius + 1, 2 * close_radius + 1)
        )
        fg_any = (
            cv2.morphologyEx(fg_any.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
            .astype(bool)
        )
    row_bands = _contiguous_bands(fg_any.any(axis=1))
    if not row_bands:
        raise ValueError("自动识别失败：整张图未检测到前景，请检查背景色/容差或改用手动行列")
    cells: list[tuple[int, int, int, int]] = []
    max_cols = 0
    for y1, y2 in row_bands:
        col_bands = _contiguous_bands(fg_any[y1:y2].any(axis=0))
        if not col_bands:
            continue
        max_cols = max(max_cols, len(col_bands))
        for x1, x2 in col_bands:
            cells.append((x1, y1, x2, y2))
    return cells, len(row_bands), max_cols


def _manual_grid_cells(
    height: int, width: int, rows: int, cols: int, inset: int
) -> list[tuple[int, int, int, int]]:
    """按行列均分生成单元格 [x1,y1,x2,y2)，并内缩 inset 像素避开外框。"""
    if rows < 1 or cols < 1:
        raise ValueError("行数/列数必须 ≥ 1")
    cells: list[tuple[int, int, int, int]] = []
    ch, cw = height // rows, width // cols
    for i in range(rows):
        for j in range(cols):
            x1, y1 = j * cw, i * ch
            x2 = width if j == cols - 1 else (j + 1) * cw
            y2 = height if i == rows - 1 else (i + 1) * ch
            x1, y1, x2, y2 = x1 + inset, y1 + inset, x2 - inset, y2 - inset
            if x2 - x1 >= 2 and y2 - y1 >= 2:
                cells.append((x1, y1, x2, y2))
    return cells


def _cut_cell(
    cell_bgr: np.ndarray,
    cell_bg: np.ndarray,
    close_radius: int,
    min_area: int,
    padding: int,
    feather: int,
) -> np.ndarray | None:
    """处理单个单元格：去底 → 合并部件 → 过滤 → 贴边裁切，返回 BGRA 或 None（空格）。"""
    ch, cw = cell_bg.shape
    # 外部连通域去底：仅清除接触单元格边界的背景色连通域，
    # 内部同色像素（黑色剑柄、深色阴影）所在连通域不接触边界，自动保留。
    n, labels, stats, _ = cv2.connectedComponentsWithStats(
        cell_bg.astype(np.uint8), connectivity=4
    )
    bg_final = np.zeros((ch, cw), dtype=bool)
    for i in range(1, n):
        x, y, bw, bh, _area = stats[i]
        if x == 0 or y == 0 or x + bw == cw or y + bh == ch:
            bg_final[labels == i] = True

    fg = (~bg_final).astype(np.uint8)
    if not fg.any():
        return None

    # 闭运算：把贴着主体的碎部件（光效、电弧）粘成同一连通域，
    # 使其在后续面积过滤中随主体一起保留。
    if close_radius > 0:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * close_radius + 1, 2 * close_radius + 1)
        )
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel)

    n2, labels2, stats2, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    keep_ids = [i for i in range(1, n2) if int(stats2[i, cv2.CC_STAT_AREA]) >= min_area]
    if not keep_ids:
        return None

    xs1 = [int(stats2[i, cv2.CC_STAT_LEFT]) for i in keep_ids]
    ys1 = [int(stats2[i, cv2.CC_STAT_TOP]) for i in keep_ids]
    xs2 = [xs1[k] + int(stats2[i, cv2.CC_STAT_WIDTH]) for k, i in enumerate(keep_ids)]
    ys2 = [ys1[k] + int(stats2[i, cv2.CC_STAT_HEIGHT]) for k, i in enumerate(keep_ids)]

    bx1 = max(0, min(xs1) - padding)
    by1 = max(0, min(ys1) - padding)
    bx2 = min(cw, max(xs2) + padding)
    by2 = min(ch, max(ys2) + padding)

    # 羽化只作用于保留部件，被过滤的标号/水印像素保持透明
    alpha = np.isin(labels2, keep_ids).astype(np.uint8) * 255
    if feather > 0:
        alpha = cv2.GaussianBlur(alpha, (0, 0), sigmaX=float(feather))
        # 外扩裁切让羽化过渡完整落在图内
        extra = 2 * feather
        bx1, by1 = max(0, bx1 - extra), max(0, by1 - extra)
        bx2, by2 = min(cw, bx2 + extra), min(ch, by2 + extra)

    crop_bgr = cell_bgr[by1:by2, bx1:bx2]
    crop_alpha = alpha[by1:by2, bx1:bx2]
    return cv2.merge(
        [
            crop_bgr[:, :, 0],
            crop_bgr[:, :, 1],
            crop_bgr[:, :, 2],
            crop_alpha,
        ]
    )


def handler(params, context, **kwargs):
    image_path = str(params.get("image_path") or "").strip()
    if not image_path:
        raise ValueError("请指定 image_path 精灵图路径（支持文件或文件夹）")
    src = Path(image_path)
    if not src.exists():
        raise FileNotFoundError(f"路径不存在: {src}")

    if src.is_dir():
        return _run_batch(src, params)
    return _run_single(src, params)


def _resolve_output_root(params, src: Path) -> Path:
    """解析输出根目录：默认输出到输入路径所在目录（单图=图片所在文件夹，批量=所选文件夹本身）。"""
    out_dir = str(params.get("output_dir") or "").strip()
    if out_dir:
        return Path(out_dir)
    return src if src.is_dir() else src.parent


def _run_batch(folder: Path, params) -> dict:
    """文件夹批量模式：扫描文件夹内所有图片逐张切图，单张失败不中断整体。"""
    files = sorted(
        p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    if not files:
        raise ValueError(
            f"文件夹中未找到图片（支持 {'、'.join(sorted(IMAGE_EXTS))}）: {folder}"
        )

    out_root = _resolve_output_root(params, folder)
    out_root.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    per_file: list[dict] = []
    errors: list[dict] = []
    total = 0
    skipped = 0
    for f in files:
        try:
            res = _run_single(f, params, out_dir=out_root / f.stem)
        except Exception as exc:  # noqa: BLE001 — 单张失败不中断批量
            errors.append({"image": str(f), "error": str(exc)})
            continue
        total += int(res["count"])
        skipped += int(res["skipped"])
        paths.extend(res["paths"])
        per_file.append(
            {
                "image": str(f.resolve()),
                "output_dir": res["output_dir"],
                "count": res["count"],
                "skipped": res["skipped"],
                "rows": res["rows"],
                "cols": res["cols"],
            }
        )

    return {
        "output_dir": str(out_root.resolve()),
        "count": total,
        "skipped": skipped,
        "rows": per_file[0]["rows"] if per_file else 0,
        "cols": per_file[0]["cols"] if per_file else 0,
        "paths": paths,
        "sheets": len(files),
        "per_file": per_file,
        "errors": errors,
    }


def _run_single(src: Path, params, out_dir: Path | None = None) -> dict:
    if not src.is_file():
        raise FileNotFoundError(f"图片不存在: {src}")

    # imdecode/imencode 走字节流，兼容 Windows 非 ASCII 路径
    raw = np.fromfile(str(src), dtype=np.uint8)
    data = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
    if data is None:
        raise ValueError(f"图片解码失败: {src}")

    if data.ndim == 2:
        data = cv2.cvtColor(data, cv2.COLOR_GRAY2BGR)
    has_alpha = data.ndim == 3 and data.shape[2] == 4
    bgr = data[:, :, :3] if has_alpha else data

    bg_bgr = _parse_bg_color(params.get("bg_color")) or _auto_bg_color(bgr)
    tolerance = int(params.get("tolerance") if params.get("tolerance") is not None else 15)
    tolerance = max(0, tolerance)

    diff = np.abs(bgr.astype(np.int16) - np.array(bg_bgr, dtype=np.int16))
    bg_mask = (diff <= tolerance).all(axis=2)
    if has_alpha:
        # 已有透明像素直接视为背景
        bg_mask |= data[:, :, 3] == 0

    grid_mode = str(params.get("grid_mode") or "manual")
    close_radius = max(
        0, int(params.get("close_radius") if params.get("close_radius") is not None else 2)
    )
    if grid_mode == "auto":
        cells, rows, cols = _detect_grid_cells(~bg_mask, close_radius=close_radius)
    else:
        rows = int(params.get("rows") if params.get("rows") is not None else 3)
        cols = int(params.get("cols") if params.get("cols") is not None else 3)
        inset_used = max(0, int(params.get("inset_margin") if params.get("inset_margin") is not None else 2))
        h, w = bgr.shape[:2]
        cells = _manual_grid_cells(h, w, rows, cols, inset_used)

    padding = max(0, int(params.get("padding") if params.get("padding") is not None else 0))
    feather = max(0, int(params.get("feather") if params.get("feather") is not None else 1))

    min_area = int(params.get("min_area") if params.get("min_area") is not None else 0)
    if min_area <= 0:
        # 自动阈值：按最大单元格面积的 1% 过滤标号/水印，下限 16px
        min_area = 16
        if cells:
            max_cell = max((c[2] - c[0]) * (c[3] - c[1]) for c in cells)
            min_area = max(min_area, int(max_cell * 0.01))

    out_path = out_dir if out_dir is not None else _resolve_output_root(params, src)
    out_path.mkdir(parents=True, exist_ok=True)

    paths: list[str] = []
    skipped = 0
    for x1, y1, x2, y2 in cells:
        result = _cut_cell(
            bgr[y1:y2, x1:x2],
            bg_mask[y1:y2, x1:x2],
            close_radius=close_radius,
            min_area=min_area,
            padding=padding,
            feather=feather,
        )
        if result is None:
            skipped += 1
            continue
        name = f"{src.stem}_r{y1:03d}c{x1:03d}.png"
        target = out_path / name
        ok, buf = cv2.imencode(".png", result)
        if not ok:
            raise ValueError(f"PNG 编码失败: {target}")
        buf.tofile(str(target))
        paths.append(str(target.resolve()))

    return {
        "output_dir": str(out_path.resolve()),
        "count": len(paths),
        "skipped": skipped,
        "rows": int(rows),
        "cols": int(cols),
        "paths": paths,
        "sheets": 1,
        "per_file": [
            {
                "image": str(src.resolve()),
                "output_dir": str(out_path.resolve()),
                "count": len(paths),
                "skipped": skipped,
                "rows": int(rows),
                "cols": int(cols),
            }
        ],
        "errors": [],
    }
