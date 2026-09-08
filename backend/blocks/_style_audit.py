"""样式审计测量核心：纯像素/几何测量，无屏幕与桌面副作用。

设计口径（docs/style_audit.md）：工具负责测量和取证，结论由调用方 AI 复核。
进 PIL RGBA 图 + OCR 词框（同 ocr_recognize 的 boxes 结构），出 JSON 报告；
不做 VLM 调用，不做合格/不合格二值判断。
"""

from __future__ import annotations

import io
import json
from pathlib import Path

KNOWN_CHECKS = ("edge_clipping", "occlusion", "low_contrast")
SEVERITY_ORDER = {"high": 0, "medium": 1, "info": 2}
# 低于该对比度无论阈值如何都判 error（WCAG 全失效区间）
_CONTRAST_ERROR_RATIO = 2.5
# 相交面积占较小框的比例超过该值才视为互相遮挡
_OVERLAP_RATIO = 0.35
# 对比度检查的最小有效框（含外扩环）：OCR 假阳性/亚像素级框的数值无意义
_CONTRAST_MIN_AREA = 100
_CONTRAST_MIN_PIXELS = 24
# 文字性预滤（N8）：框内 Otsu 少数侧（"墨水"）占比过低判非文字——
# 覆盖近空白（噪点/反色误检）与单色实心块（金纹分隔条、纯色带等：
# 它们要么整体同色、要么底色占绝对主导，少数侧都趋近 0）。
# 两种色调混合的重复图案纹理不在本启发覆盖范围内，confidence 已随
# texts[] 输出供下游过滤。
_INK_RATIO_MIN = 0.05
_DEFAULT_MIN_TEXT_HEIGHT = 8
# 单张图上 issue 数上限，防止病态输入刷屏
_DEFAULT_MAX_ISSUES = 30


def parse_checks(value, *, default=",".join(KNOWN_CHECKS)) -> list[str]:
    raw = str(value or "").strip() or default
    checks = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = [c for c in checks if c not in KNOWN_CHECKS]
    if unknown:
        raise ValueError(f"未知检查项: {'、'.join(unknown)}（支持: {', '.join(KNOWN_CHECKS)}）")
    if not checks:
        raise ValueError("checks 不能为空")
    return checks


def load_image(path: str):
    """从文件路径加载 RGBA PIL 图。"""
    from PIL import Image

    p = Path(str(path or "").strip())
    if not p.is_file():
        raise ValueError(f"图片文件不存在: {p}")
    try:
        img = Image.open(p)
        img.load()
    except Exception as exc:
        raise ValueError(f"无法打开图片: {p} ({exc})") from exc
    return img.convert("RGBA")


def parse_text_boxes(raw) -> list[dict]:
    """解析外部传入的 OCR 词框 JSON（custom 模式），输出结构与 ocr_recognize.boxes 对齐。"""
    if raw is None or str(raw).strip() == "":
        return []
    try:
        data = json.loads(str(raw))
    except Exception as exc:
        raise ValueError(f"text_boxes 不是合法 JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("text_boxes 必须是 JSON 数组")
    boxes: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            left = int(round(float(item.get("left", 0))))
            top = int(round(float(item.get("top", 0))))
            width = int(round(float(item.get("width", 0))))
            height = int(round(float(item.get("height", 0))))
        except (TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        boxes.append(
            {
                "text": str(item.get("text") or ""),
                "confidence": float(item.get("confidence") or 0.0),
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            }
        )
    return boxes


def run_text_ocr(img, *, min_confidence: float = 0.3) -> list[dict]:
    """内置 OCR：复用 ocr_recognize 的推理链路，返回图像本地坐标词框。"""
    import numpy as np

    from backend.blocks.ocr_recognize import (
        _compact_box,
        _infer_ocr,
        _prepare_ocr_image,
    )
    from backend.blocks._ocr_match import aabb_from_polygon

    ocr_img, scale_x, scale_y = _prepare_ocr_image(img)
    # RapidOCR 视裸 ndarray 为 BGR；PIL 像素是 RGB——显式翻转。
    arr = np.ascontiguousarray(np.asarray(ocr_img))
    if arr.ndim == 3 and arr.shape[2] >= 3:
        arr = np.ascontiguousarray(arr[:, :, ::-1])
    try:
        result, _elapsed = _infer_ocr(arr)
    finally:
        del arr

    if not result:
        return []
    inv_x = 1.0 / scale_x if scale_x and abs(scale_x - 1.0) > 1e-6 else 1.0
    inv_y = 1.0 / scale_y if scale_y and abs(scale_y - 1.0) > 1e-6 else 1.0
    boxes: list[dict] = []
    for item in result:
        if not item or len(item) < 3:
            continue
        box, text, score = item[0], str(item[1]), float(item[2])
        if score < min_confidence:
            continue
        poly = _compact_box(box)
        if (inv_x != 1.0 or inv_y != 1.0) and poly:
            poly = [
                [int(round(pt[0] * inv_x)), int(round(pt[1] * inv_y))]
                for pt in poly
            ]
        geom = aabb_from_polygon(poly)
        boxes.append(
            {
                "text": text,
                "confidence": round(score, 4),
                "left": int(geom["left"]),
                "top": int(geom["top"]),
                "width": int(geom["width"]),
                "height": int(geom["height"]),
            }
        )
    return boxes


def _box_rect(box: dict) -> tuple[int, int, int, int]:
    return int(box["left"]), int(box["top"]), int(box["left"] + box["width"]), int(box["top"] + box["height"])


def annotate_text_likeness(img, boxes: list[dict], *, min_height: int = _DEFAULT_MIN_TEXT_HEIGHT) -> list[dict]:
    """文字性预滤（auto 模式）：给每个词框标注 filtered=None（正常）或原因串。

    启发：最小字高 + 框内 Otsu 少数侧"墨水"占比（近空白/单色实心块判非文字）。
    两种色调混合的重复图案纹理暂不判别，confidence 已随 texts[] 输出供下游过滤。
    框过小或过透明到无法判断时保持 None（宁可放过不误杀）。
    """
    import numpy as np

    arr = np.asarray(img.convert("RGBA"))
    out: list[dict] = []
    for box in boxes:
        b = dict(box)
        b["filtered"] = None
        height = int(box.get("height") or 0)
        if min_height > 0 and 0 < height < min_height:
            b["filtered"] = f"字高 {height}px < {min_height}px"
            out.append(b)
            continue
        left, top, right, bottom = _box_rect(box)
        left, top = _clamp(left, 0, arr.shape[1] - 1), _clamp(top, 0, arr.shape[0] - 1)
        right, bottom = _clamp(right, left + 1, arr.shape[1]), _clamp(bottom, top + 1, arr.shape[0])
        if (right - left) * (bottom - top) < _CONTRAST_MIN_AREA:
            out.append(b)
            continue
        crop = arr[top:bottom, left:right]
        px = crop[crop[:, :, 3] > 8]
        if px.shape[0] < _CONTRAST_MIN_PIXELS:
            out.append(b)
            continue
        lum_u8 = _luminance(px).astype(np.uint8)
        hist = np.bincount(lum_u8, minlength=256)
        t = _otsu_threshold([int(x) for x in hist], int(px.shape[0]))
        ink = min(int((lum_u8 > t).sum()), int((lum_u8 <= t).sum())) / float(px.shape[0])
        if ink < _INK_RATIO_MIN:
            b["filtered"] = f"墨水占比 {ink:.2f} 过低（近空白/实心色块）"
        out.append(b)
    return out


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


# ---------------------------------------------------------------- edge checks

def check_edges(boxes, width: int, height: int, margin_px: int, origin: tuple[int, int]) -> list[dict]:
    """文字框超出画布 / 贴边。超出判 high，贴边判 info（可能是刻意满铺）。

    报告的是真实溢出像素；margin_px 只作为判定门槛（溢出 ≤ 容差不报 out_of_canvas）。
    """
    issues: list[dict] = []
    for box in boxes:
        left, top, right, bottom = _box_rect(box)
        over = {
            "左": -left,
            "上": -top,
            "右": right - width,
            "下": bottom - height,
        }
        worst = max(over.values())
        if worst > margin_px:
            sides = [f"{name}超出 {val}px" for name, val in over.items() if val > 0]
            issues.append(_issue(
                "text_out_of_canvas", "high", box, origin,
                "文字框超出图像边界，疑似被裁剪或坐标错位",
                detail="；".join(sides),
            ))
            continue
        dist = min(left, top, width - right, height - bottom)
        if dist <= margin_px:
            issues.append(_issue(
                "text_edge_flush", "info", box, origin,
                "文字框紧贴图像边缘，可能是刻意满铺，也可能是裁剪/溢出残留",
                detail=f"距边缘 {dist}px（容差 {margin_px}px）",
            ))
    return issues


def check_overlap(boxes, origin: tuple[int, int]) -> list[dict]:
    """文字框两两相交：相交面积占较小框比例超阈值 → 疑似互相遮挡。"""
    issues: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            ix = max(0, min(a["left"] + a["width"], b["left"] + b["width"]) - max(a["left"], b["left"]))
            iy = max(0, min(a["top"] + a["height"], b["top"] + b["height"]) - max(a["top"], b["top"]))
            inter = ix * iy
            if inter <= 0:
                continue
            smaller = min(a["width"] * a["height"], b["width"] * b["height"])
            if smaller <= 0 or inter / smaller < _OVERLAP_RATIO:
                continue
            key = (min(i, j), max(i, j))
            if key in seen:
                continue
            seen.add(key)
            issues.append(_issue(
                "text_overlap", "high", a, origin,
                f"文字「{a.get('text') or '?'}」与「{b.get('text') or '?'}」框体大面积相交，疑似互相遮挡",
                detail=f"交叠 {round(inter / smaller * 100)}%",
                extra_box=b,
            ))
    return issues


# ------------------------------------------------------------- contrast check

def _wcag_luminance(rgb) -> float:
    def lin(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb[0], rgb[1], rgb[2]
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_ratio(color_a, color_b) -> float:
    la, lb = _wcag_luminance(color_a), _wcag_luminance(color_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _otsu_threshold(hist: list[int], total: int) -> int:
    best_t, best_var = 0, -1.0
    w0 = 0.0
    sum0 = 0.0
    total_sum = float(sum(i * h for i, h in enumerate(hist)))
    for t in range(256):
        w0 += hist[t]
        if w0 == 0:
            continue
        w1 = total - w0
        if w1 == 0:
            break
        sum0 += t * hist[t]
        mean0 = sum0 / w0
        mean1 = (total_sum - sum0) / w1
        var = w0 * w1 * (mean0 - mean1) ** 2
        if var > best_var:
            best_var, best_t = var, t
    return best_t


def _hex(rgb) -> str:
    r, g, b = (int(round(float(c))) for c in rgb[:3])
    return f"#{max(0, min(255, r)):02X}{max(0, min(255, g)):02X}{max(0, min(255, b)):02X}"


def _luminance(px):
    """(N,3+) 像素数组 → WCAG 相对亮度（0-255 线性加权，供 Otsu 分割）。"""
    import numpy as np

    return (
        0.2126 * px[:, 0].astype(np.float32)
        + 0.7152 * px[:, 1].astype(np.float32)
        + 0.0722 * px[:, 2].astype(np.float32)
    )


def measure_contrast(arr, box: dict) -> dict | None:
    """文字对比度测量（v2 口径）：框内 Otsu 分离笔画，背景取外扩环异侧像素。

    采样规则：
    - 阈值：优先由框内像素 Otsu 决定（文字笔画主导，不受外扩环里的相邻元素
      干扰）；框内单色或不可用时退回整个外扩 crop 的 Otsu（v1 口径）。
    - 前景：框内阈值少数侧像素（文字笔画几乎总是少数侧）；框内全在一侧时
      取整框平均色。
    - 背景：优先取外扩环中与前景异侧的像素——天然排除环内与文字同色调的
      相邻元素（席位圆点、阴影边）；环过小时退回 crop 内异侧（v1 口径）。
    返回 {"ratio", "fg", "bg", "threshold"}；不可测返回 None。
    """
    import numpy as np

    left, top, right, bottom = _box_rect(box)
    pad = max(2, int(box["height"]) // 3)
    left, top = _clamp(left - pad, 0, arr.shape[1] - 1), _clamp(top - pad, 0, arr.shape[0] - 1)
    right, bottom = _clamp(right + pad, 1, arr.shape[1]), _clamp(bottom + pad, 1, arr.shape[0])
    if (right - left) * (bottom - top) < _CONTRAST_MIN_AREA:
        return None
    crop = arr[top:bottom, left:right]
    alpha = crop[:, :, 3] > 8
    pixels = crop[alpha]
    if pixels.shape[0] < _CONTRAST_MIN_PIXELS:
        return None
    # 阈值与两侧分割统一在 uint8 量化亮度空间（与直方图同口径，浮点亮度
    # 直接与整型阈值比较会在 bin 边界上把一侧清空）
    lum_u8 = _luminance(pixels).astype(np.uint8)

    # 内框 / 外扩环（与图像边界求交后的实际区域）
    ix1 = max(0, int(box["left"])) - left
    iy1 = max(0, int(box["top"])) - top
    ix2 = min(arr.shape[1], int(box["left"]) + int(box["width"])) - left
    iy2 = min(arr.shape[0], int(box["top"]) + int(box["height"])) - top
    yy, xx = np.mgrid[0:crop.shape[0], 0:crop.shape[1]]
    inner_mask = (xx >= ix1) & (xx < ix2) & (yy >= iy1) & (yy < iy2) & alpha
    inner_px = crop[inner_mask]
    ring_px = crop[(~inner_mask) & alpha]

    if inner_px.shape[0] >= _CONTRAST_MIN_PIXELS:
        inner_u8 = _luminance(inner_px).astype(np.uint8)
        if int(inner_u8.min()) != int(inner_u8.max()):
            hist = np.bincount(inner_u8, minlength=256)
            threshold = _otsu_threshold([int(x) for x in hist], int(inner_px.shape[0]))
        else:
            # 框内单色：阈值由 crop 整体二分（框 vs 环）
            hist = np.bincount(lum_u8, minlength=256)
            threshold = _otsu_threshold([int(x) for x in hist], int(pixels.shape[0]))
        hi = inner_u8 > threshold
        n_hi, n_lo = int(hi.sum()), int((~hi).sum())
        if n_hi == 0 or n_lo == 0:
            fg = inner_px.mean(axis=0)
            fg_hi = n_lo == 0
        else:
            fg_hi = n_hi <= n_lo
            fg = inner_px[hi if fg_hi else ~hi].mean(axis=0)
        if ring_px.shape[0] >= _CONTRAST_MIN_PIXELS:
            ring_u8 = _luminance(ring_px).astype(np.uint8)
            bg_sel = ring_u8 <= threshold if fg_hi else ring_u8 > threshold
            bg = ring_px[bg_sel].mean(axis=0) if bool(bg_sel.any()) else ring_px.mean(axis=0)
        else:
            bg_sel = lum_u8 <= threshold if fg_hi else lum_u8 > threshold
            bg = pixels[bg_sel].mean(axis=0)
    else:
        # v1 口径：整 crop Otsu，少数侧为前景
        hist = np.bincount(lum_u8, minlength=256)
        threshold = _otsu_threshold([int(x) for x in hist], int(pixels.shape[0]))
        fg_hi_mask = lum_u8 > threshold
        if fg_hi_mask.all() or (~fg_hi_mask).all():
            return None
        fg_hi = int(fg_hi_mask.sum()) <= int((~fg_hi_mask).sum())
        fg = pixels[fg_hi_mask if fg_hi else ~fg_hi_mask].mean(axis=0)
        bg = pixels[~fg_hi_mask if fg_hi else fg_hi_mask].mean(axis=0)
    return {
        "ratio": contrast_ratio(fg, bg),
        "fg": _hex(fg),
        "bg": _hex(bg),
        "threshold": int(threshold),
    }


def measure_contrast_all(arr, boxes: list[dict]) -> list[dict | None]:
    """逐框测量对比度，与 boxes 等长对齐（不可测的框为 None）。"""
    return [measure_contrast(arr, box) for box in boxes]


def check_contrast(
    measurements: list[dict | None], boxes: list[dict], threshold: float, origin: tuple[int, int]
) -> list[dict]:
    issues: list[dict] = []
    for box, m in zip(boxes, measurements):
        if m is None:
            continue
        ratio = float(m["ratio"])
        if ratio >= threshold:
            continue
        severity = "high" if ratio < _CONTRAST_ERROR_RATIO else "medium"
        issues.append(_issue(
            "text_low_contrast", severity, box, origin,
            "文字与其所在背景的对比度偏低，弱视/强光场景可能难以辨认",
            detail=(
                f"WCAG 对比度 {ratio:.2f} < {threshold:.2f}"
                f"（fg {m['fg']} / bg {m['bg']}，Otsu 阈值 {m['threshold']}）"
            ),
        ))
    return issues


# -------------------------------------------------------------------- palette

def extract_palette(img, k: int) -> dict:
    """主色提取（忽略透明像素）+ 边框环主色作背景估计。"""
    from PIL import Image

    rgba = img.convert("RGBA")
    width, height = rgba.size
    rgb = rgba.convert("RGB")
    alpha = rgba.getchannel("A")
    transparent_ratio = 1.0 - (sum(alpha.histogram()[8:]) / float(width * height))

    # 主色：median-cut 量化后按占比统计
    colors: list[dict] = []
    if width * height > 0 and k > 0:
        sample = rgb if width * height <= 262144 else rgb.resize((512, max(1, height * 512 // width)))
        q = sample.quantize(colors=max(1, k), method=Image.MEDIANCUT)
        pal = q.getpalette() or []
        counts = sorted(q.getcolors(maxcolors=max(1, k)) or [], reverse=True)
        total = sum(c for c, _ in counts) or 1
        for count, idx in counts[:k]:
            r, g, b = pal[idx * 3: idx * 3 + 3]
            colors.append(
                {"hex": f"#{r:02X}{g:02X}{b:02X}", "rgb": [int(r), int(g), int(b)], "ratio": round(count / total, 4)}
            )

    # 背景：四边 1px 环的主色；环主体透明则视为透明画布（只统计不透明像素）
    import numpy as np

    arr = np.asarray(rgba)
    ring = (
        [tuple(arr[0, x]) for x in range(width)]
        + [tuple(arr[height - 1, x]) for x in range(width)]
        + [tuple(arr[y, 0]) for y in range(height)]
        + [tuple(arr[y, width - 1][:3]) for y in range(height)]
    ) if width > 1 and height > 1 else []
    background = None
    if ring:
        opaque = [c for c in ring if len(c) >= 4 and c[3] > 8]
        if opaque and len(opaque) / len(ring) > 0.6:
            quant: dict[tuple[int, int, int], int] = {}
            for r, g, b, *_ in opaque:
                key = (r // 16, g // 16, b // 16)
                quant[key] = quant.get(key, 0) + 1
            (r, g, b), hits = max(quant.items(), key=lambda kv: kv[1])
            if hits / max(1, len(opaque)) > 0.6:
                background = f"#{r * 16:02X}{g * 16:02X}{b * 16:02X}"
    return {
        "colors": colors,
        "background": background,
        "transparent_ratio": round(transparent_ratio, 4),
    }


# ------------------------------------------------------------------ reporting

def _issue(itype: str, severity: str, box: dict, origin: tuple[int, int], message: str, *, detail: str = "", extra_box: dict | None = None) -> dict:
    ox, oy = origin
    out = {
        "type": itype,
        "severity": severity,
        "message": message,
        "text": str(box.get("text") or ""),
        "left": int(box["left"]) + ox,
        "top": int(box["top"]) + oy,
        "width": int(box["width"]),
        "height": int(box["height"]),
    }
    if detail:
        out["detail"] = detail
    if extra_box is not None:
        out["other_box"] = {
            "text": str(extra_box.get("text") or ""),
            "left": int(extra_box["left"]) + ox,
            "top": int(extra_box["top"]) + oy,
            "width": int(extra_box["width"]),
            "height": int(extra_box["height"]),
        }
    return out


def annotate(img, issues, out_path: str, origin: tuple[int, int]) -> str:
    """按严重度着色标注问题框：红=high、橙=medium、黄=info。返回落盘路径。"""
    from PIL import Image, ImageDraw

    ox, oy = origin
    canvas = img.convert("RGBA").copy()
    draw = ImageDraw.Draw(canvas)
    colors = {"high": (230, 50, 50, 255), "medium": (240, 150, 30, 255), "info": (230, 210, 40, 255)}
    for idx, issue in enumerate(issues, 1):
        color = colors.get(str(issue.get("severity")), colors["info"])
        rects = [{"left": issue["left"], "top": issue["top"], "width": issue["width"], "height": issue["height"]}]
        if isinstance(issue.get("other_box"), dict):
            rects.append(issue["other_box"])
        for rect in rects:
            left = _clamp(int(rect["left"]) - ox, 0, canvas.width - 1)
            top = _clamp(int(rect["top"]) - oy, 0, canvas.height - 1)
            right = _clamp(int(rect["left"]) - ox + int(rect["width"]), 1, canvas.width)
            bottom = _clamp(int(rect["top"]) - oy + int(rect["height"]), 1, canvas.height)
            for w in range(2):
                draw.rectangle([left - w, top - w, right + w, bottom + w], outline=color)
            draw.text((left + 2, max(0, top - 12)), f"{idx}:{issue.get('type')}", fill=color)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(path)
    return str(path.resolve())


def save_report(report: dict, out_path: str) -> str:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.resolve())


def build_texts(boxes: list[dict], measurements: list[dict | None], origin: tuple[int, int] = (0, 0)) -> list[dict]:
    """全量文字框清单：每个候选框都带对比度取证（不可测为 null），含被过滤框。

    坐标加 origin 偏移，与 issues 保持同一口径（原图/屏幕坐标）。
    """
    ox, oy = origin
    out: list[dict] = []
    for box, m in zip(boxes, measurements):
        out.append({
            "text": str(box.get("text") or ""),
            "left": int(box["left"]) + ox,
            "top": int(box["top"]) + oy,
            "width": int(box["width"]),
            "height": int(box["height"]),
            "confidence": round(float(box.get("confidence") or 0.0), 4),
            "contrast": round(float(m["ratio"]), 4) if m else None,
            "fg": m["fg"] if m else None,
            "bg": m["bg"] if m else None,
            "filtered": box.get("filtered"),
        })
    return out


def audit_image(
    img,
    *,
    text_boxes: list[dict] | None = None,
    checks: list[str] | None = None,
    margin_px: int = 2,
    contrast_threshold: float = 4.5,
    palette_size: int = 6,
    origin: tuple[int, int] = (0, 0),
    max_issues: int = _DEFAULT_MAX_ISSUES,
    annotate_path: str = "",
    save_report_path: str = "",
    ocr_error: str | None = None,
    region: list[int] | None = None,
) -> dict:
    """主入口：图 + 词框 → 测量报告。issues 按 severity 升序（high 在前）稳定排序。

    词框可带 filtered 字段（文字性预滤原因）：被滤框仍进 texts[] 留痕，
    但不参与 edge/overlap/contrast 检查。
    """
    width, height = img.size
    issues: list[dict] = []
    checks = checks or list(KNOWN_CHECKS)
    boxes = [dict(b) for b in (text_boxes or [])]
    usable = [b for b in boxes if not b.get("filtered")]
    measurements: list[dict | None] = [None] * len(boxes)

    if "low_contrast" in checks and usable:
        import numpy as np

        arr = np.asarray(img.convert("RGBA"))
        idx = [i for i, b in enumerate(boxes) if not b.get("filtered")]
        for i, m in zip(idx, measure_contrast_all(arr, [boxes[i] for i in idx])):
            measurements[i] = m
    if "edge_clipping" in checks:
        issues.extend(check_edges(usable, width, height, margin_px, origin))
    if "occlusion" in checks:
        issues.extend(check_overlap(usable, origin))
    if "low_contrast" in checks:
        ms = [m for b, m in zip(boxes, measurements) if not b.get("filtered")]
        issues.extend(check_contrast(ms, usable, contrast_threshold, origin))

    issues.sort(key=lambda i: (SEVERITY_ORDER.get(str(i.get("severity")), 3), i.get("type") or ""))
    truncated = False
    if len(issues) > max_issues:
        issues = issues[:max_issues]
        truncated = True

    palette = extract_palette(img, palette_size) if palette_size > 0 else None

    report = {
        "ok": True,
        "image": {"path": str(getattr(img, "filename", "") or ""), "width": int(width), "height": int(height)},
        "region": list(region) if region else None,
        "text_count": len(boxes),
        "filtered_count": sum(1 for b in boxes if b.get("filtered")),
        "texts": build_texts(boxes, measurements, origin),
        "issue_count": len(issues),
        "issues": issues,
        "issues_truncated": truncated,
        "checks": list(checks),
        "palette": palette,
        "ocr_error": ocr_error,
    }
    if save_report_path:
        report["report_path"] = save_report(report, save_report_path)
    if annotate_path:
        report["annotated_path"] = annotate(img, issues, annotate_path, origin)
    return report


def load_image_bytes(data: bytes):
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    img.load()
    return img.convert("RGBA")
