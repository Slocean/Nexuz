"""立绘部件切件：把一张立绘按矩形区域切成互相配套的部件层（关节偶/puppet 用）。

与「透明图自动切割 / 精灵图智能切图」的差别：那两个积木面向"把一张图拆成
多张独立素材"（各素材独立画布、贴边裁切）；本积木面向"把同一张立绘拆成
多个图层"——所有部件输出同一尺寸画布、像素画在原位置（同画布回贴），
前端把各层按 (0,0) 叠放即还原原图，旋转某层时不需要任何对位换算。

典型用法（手臂件）：
  parts = [
    {"name": "torso",      "rect": [0, 0, 400, 427], "exclude": ["arm_weapon"], "fill": true},
    {"name": "arm_weapon", "rect": [300, 80, 380, 240]},
  ]
  pivot = "332,150"   # 肩关节（旋转轴心），写入 manifest 供 transform-origin 使用

补全语义：torso 声明 exclude 后，被排除矩形内源图不透明的像素（原本被
手臂/武器遮挡的袍子）用 fill 颜色补回——fill: true 自动取该部件保留区
的主色（平涂色块立绘效果最好），也可显式指定 "#RRGGBB" 或 "R,G,B"。

manifest.json 落盘输出目录：画布尺寸、部件文件与 z 序、pivot 坐标，
外部 agent（MCP run_block）可直接读取该文件接线到 demo 页。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import cv2
import numpy as np

SCHEMA = {
    "type": "sprite_part_cut",
    "label": "立绘部件切件",
    "category": "识别类",
    "description": (
        "按矩形区域把一张立绘切成多个部件图层（同画布回贴），"
        "支持排除区补全与关节坐标 manifest，用于关节偶动画素材制作。"
    ),
    # 代码级完成日志模板：流程结束时自动拼进「流程执行完成」日志；
    # 节点上手动填写的完成日志可覆盖此模板。{{字段}} 引用本节点输出。
    "done_log": "已切出{{count}}个部件 → {{output_dir}}（manifest.json 含关节坐标）",
    "inputs": [
        {
            "name": "image_path",
            "type": "string",
            "label": "立绘路径",
            "default": "",
            "placeholder": "源立绘 PNG（建议带透明通道）",
            "ui": "file_or_dir",
            "accept": "*.png;*.webp;*.bmp",
            "bindable": True,
            "required": True,
        },
        {
            "name": "output_dir",
            "type": "string",
            "label": "输出目录",
            "default": "",
            "placeholder": "留空则输出到输入旁的 图名_puppet/ 文件夹",
            "ui": "file_or_dir",
        },
        {
            "name": "parts",
            "type": "string",
            "label": "部件区域",
            "default": "",
            "ui": "textarea",
            "placeholder": (
                "每行一个部件：名称,x1,y1,x2,y2（x2,y2 为右下角，不含）；"
                "或 JSON 数组 [{\"name\":\"arm\",\"rect\":[x1,y1,x2,y2],"
                "\"exclude\":[\"torso\"],\"fill\":true,\"fill_color\":\"#RRGGBB\"}]；"
                "fill 也可直接写颜色串"
            ),
            "bindable": True,
            "required": True,
        },
        {
            "name": "pivot",
            "type": "string",
            "label": "关节坐标",
            "default": "",
            "placeholder": "画布内 x,y（如 332,150）；留空不写入 manifest",
            "bindable": True,
        },
        {
            "name": "pivot_label",
            "type": "string",
            "label": "关节名称",
            "default": "",
            "placeholder": "如 肩关节（写入 manifest 的 pivot.label）",
        },
        {
            "name": "alpha_threshold",
            "type": "number",
            "label": "不透明判定阈值",
            "default": 10,
            "placeholder": "alpha 高于该值视为不透明 0~255",
        },
    ],
    "outputs": [
        {"name": "output_dir", "type": "string"},
        {"name": "count", "type": "number"},
        {"name": "canvas_w", "type": "number"},
        {"name": "canvas_h", "type": "number"},
        {"name": "pivot_x", "type": "number"},
        {"name": "pivot_y", "type": "number"},
        {"name": "paths", "type": "object", "itemType": "string", "canvas": False},
        {"name": "manifest_path", "type": "string"},
        {"name": "per_part", "type": "object", "canvas": False},
    ],
}

# 行格式：名称,x1,y1,x2,y2
_LINE_RE = re.compile(r"([^,，]+)[,，]\s*(-?\d+)\s*[,，]\s*(-?\d+)\s*[,，]\s*(-?\d+)\s*[,，]\s*(-?\d+)\s*$")


def _parse_parts(value) -> list[dict]:
    """部件定义归一化：接受 JSON 数组 / dict 列表 / 每行一个的多行文本。"""
    items: list = []
    if isinstance(value, (list, tuple)):
        items = list(value)
    elif isinstance(value, dict):
        items = [value]
    elif isinstance(value, str) and value.strip().startswith(("[", "{")):
        # MCP / 变量绑定可能把 JSON 数组整体传成字符串
        parsed = json.loads(value)
        items = parsed if isinstance(parsed, list) else [parsed]
    else:
        for line in str(value or "").splitlines():
            text = line.strip().rstrip(";，,")
            if not text or text.startswith("#"):
                continue
            m = _LINE_RE.match(text)
            if not m:
                raise ValueError(
                    f"部件行格式应为 名称,x1,y1,x2,y2: {line!r}"
                )
            items.append(
                {
                    "name": m.group(1).strip(),
                    "rect": [int(m.group(i)) for i in range(2, 6)],
                }
            )
    if not items:
        raise ValueError("请至少定义一个部件区域")

    parts: list[dict] = []
    seen: set[str] = set()
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise ValueError(f"第 {i + 1} 个部件定义应为对象，收到: {raw!r}")
        name = str(raw.get("name") or "").strip()
        if not name:
            raise ValueError(f"第 {i + 1} 个部件缺少 name")
        if name in seen:
            raise ValueError(f"部件名重复: {name}")
        seen.add(name)
        rect = raw.get("rect")
        if isinstance(rect, dict):
            if all(k in rect for k in ("x1", "y1", "x2", "y2")):
                rect = [rect["x1"], rect["y1"], rect["x2"], rect["y2"]]
            elif all(k in rect for k in ("x", "y", "w", "h")):
                rect = [
                    rect["x"],
                    rect["y"],
                    rect["x"] + rect["w"],
                    rect["y"] + rect["h"],
                ]
            else:
                rect = None
        if not isinstance(rect, (list, tuple)) or len(rect) != 4:
            raise ValueError(f"部件 {name} 缺少 rect（[x1,y1,x2,y2] 或 {{x,y,w,h}}）")
        try:
            x1, y1, x2, y2 = (int(float(v)) for v in rect)
        except (TypeError, ValueError):
            raise ValueError(f"部件 {name} 的 rect 含非数字: {rect!r}") from None
        exclude = [str(e).strip() for e in (raw.get("exclude") or []) if str(e).strip()]
        fill = raw.get("fill")
        fill_color = str(raw.get("fill_color") or "").strip()
        # 便捷写法：fill 直接给颜色串（"#RRGGBB" / "R,G,B"）视作显式补全色
        if isinstance(fill, str) and fill.strip() and fill.strip().lower() not in {"true", "false", "1", "0"}:
            fill_color = fill_color or fill.strip()
            fill = True
        parts.append(
            {
                "name": name,
                "rect": (x1, y1, x2, y2),
                "exclude": exclude,
                "fill": bool(fill if fill is not None else bool(exclude)),
                "fill_color": fill_color,
                "feather": max(0, int(float(raw.get("feather") or 0))),
            }
        )
    for part in parts:
        for ex in part["exclude"]:
            if ex not in seen:
                raise ValueError(f"部件 {part['name']} 的 exclude 引用了不存在的部件: {ex}")
            if ex == part["name"]:
                raise ValueError(f"部件 {part['name']} 不能 exclude 自己")
    return parts


def _parse_pivot(value) -> tuple[int, int] | None:
    text = str(value or "").strip()
    if not text:
        return None
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)$", text)
    if not m:
        raise ValueError(f"关节坐标格式应为 x,y: {text!r}")
    return int(float(m.group(1))), int(float(m.group(2)))


def _parse_color(text: str) -> tuple[int, int, int] | None:
    """颜色解析（RGB 语义），返回 BGR；空返回 None。"""
    t = str(text or "").strip()
    if not t:
        return None
    if t.startswith("#"):
        hexval = t[1:]
        if len(hexval) != 6:
            raise ValueError(f"颜色格式应为 #RRGGBB，收到: {text}")
        r, g, b = (int(hexval[i : i + 2], 16) for i in (0, 2, 4))
        return (b, g, r)
    parts = re.split(r"[,\s]+", t)
    if len(parts) != 3:
        raise ValueError(f"颜色格式应为 #RRGGBB 或 R,G,B，收到: {text}")
    rgb = tuple(int(p) for p in parts)
    for v in rgb:
        if not 0 <= v <= 255:
            raise ValueError(f"颜色分量超出 0~255: {text}")
    return (rgb[2], rgb[1], rgb[0])  # type: ignore[return-value]


def _dominant_color(bgr: np.ndarray, opaque: np.ndarray) -> tuple[int, int, int]:
    """区域内不透明像素的主色（平涂色块立绘的袍子/皮肤色）。"""
    pixels = bgr[opaque]
    if pixels.size == 0:
        raise ValueError("部件保留区没有不透明像素，无法自动取补全色，请显式指定 fill_color")
    quant = (pixels // 16).astype(np.int32)
    keys = quant[:, 0] * 4096 + quant[:, 1] * 64 + quant[:, 2]
    vals, counts = np.unique(keys, return_counts=True)
    key = int(vals[np.argmax(counts)])
    bucket = pixels[(keys == key)]
    return tuple(int(v) for v in np.median(bucket, axis=0))  # type: ignore[return-value]


def handler(params, context, **kwargs):
    src = Path(str(params.get("image_path") or "").strip().strip('"'))
    if not src.name:
        raise ValueError("请指定 image_path 立绘路径")
    if not src.is_file():
        raise FileNotFoundError(f"立绘不存在: {src}")

    # imdecode/imencode 走字节流，兼容 Windows 非 ASCII 路径
    raw = np.fromfile(str(src), dtype=np.uint8)
    data = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
    if data is None:
        raise ValueError(f"图片解码失败: {src}")
    if data.ndim == 2:
        data = cv2.cvtColor(data, cv2.COLOR_GRAY2BGRA)
    if data.shape[2] == 3:
        data = cv2.cvtColor(data, cv2.COLOR_BGR2BGRA)
    canvas_h, canvas_w = data.shape[:2]
    bgr = data[:, :, :3]
    alpha = data[:, :, 3]
    alpha_raw = params.get("alpha_threshold")
    alpha_threshold = max(
        0, min(255, int(float(alpha_raw if alpha_raw not in (None, "") else 10)))
    )
    opaque = alpha > alpha_threshold

    parts = _parse_parts(params.get("parts"))
    pivot = _parse_pivot(params.get("pivot"))
    pivot_label = str(params.get("pivot_label") or "").strip()

    out_dir = Path(str(params.get("output_dir") or "").strip()) if str(params.get("output_dir") or "").strip() else src.parent / f"{src.stem}_puppet"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 各部件排除区预求交：exclude 区域 = 对方 rect 与本部件 rect 的交集
    rect_masks: dict[str, np.ndarray] = {}
    for part in parts:
        x1, y1, x2, y2 = part["rect"]
        mask = np.zeros((canvas_h, canvas_w), dtype=bool)
        cx1, cy1 = max(0, x1), max(0, y1)
        cx2, cy2 = min(canvas_w, x2), min(canvas_h, y2)
        if cx2 > cx1 and cy2 > cy1:
            mask[cy1:cy2, cx1:cx2] = True
        part["_clamped"] = (cx1, cy1, cx2, cy2)
        rect_masks[part["name"]] = mask

    paths: dict[str, str] = {}
    per_part: list[dict] = []
    for part in parts:
        keep = rect_masks[part["name"]].copy()
        excluded_total = np.zeros_like(keep)
        for ex in part["exclude"]:
            excluded_total |= rect_masks[ex]
        keep &= ~excluded_total

        if part["fill"]:
            holes = rect_masks[part["name"]] & excluded_total & opaque
        else:
            holes = np.zeros_like(keep)

        if not keep.any() and not holes.any():
            raise ValueError(
                f"部件 {part['name']} 的区域完全落在画布外或被排除区完全覆盖: {part['rect']}"
            )

        out = np.zeros((canvas_h, canvas_w, 4), dtype=np.uint8)
        fill_bgr = _parse_color(part["fill_color"])
        if holes.any():
            if fill_bgr is None:
                fill_bgr = _dominant_color(bgr, keep & opaque)
            out[holes] = (*fill_bgr, 255)

        visible = keep & opaque
        out[visible, :3] = bgr[visible]
        out[visible, 3] = alpha[visible]

        feather = part["feather"]
        if feather > 0:
            a = cv2.GaussianBlur(out[:, :, 3], (0, 0), sigmaX=float(feather))
            # 羽化只作用于保留区边缘；补全区是合成的平涂色，保持硬 alpha
            a = np.where(keep & opaque, a, 0)
            a[holes] = 255
            out[:, :, 3] = a.astype(np.uint8)

        name = part["name"]
        # 部件名作为文件名使用，拦截路径分隔符
        safe_name = re.sub(r'[\\/:*?"<>|]+', "_", name)
        target = out_dir / f"{safe_name}.png"
        ok, buf = cv2.imencode(".png", out)
        if not ok:
            raise ValueError(f"PNG 编码失败: {target}")
        buf.tofile(str(target))
        paths[name] = str(target.resolve())

        cx1, cy1, cx2, cy2 = part["_clamped"]
        per_part.append(
            {
                "name": name,
                "file": target.name,
                "rect": list(part["rect"]),
                "clamped_rect": [cx1, cy1, cx2, cy2],
                "exclude": list(part["exclude"]),
                "fill": bool(part["fill"]),
                "filled_pixels": int(holes.sum()),
                "kept_pixels": int(visible.sum()),
                "bbox": [
                    int(cx1),
                    int(cy1),
                    int(cx2),
                    int(cy2),
                ],
            }
        )

    pivot_x, pivot_y = (pivot if pivot else (None, None))
    manifest = {
        "source": str(src.resolve()),
        "canvas": {"width": canvas_w, "height": canvas_h},
        "pivot": (
            {
                "x": pivot_x,
                "y": pivot_y,
                "label": pivot_label or None,
                "part": _pivot_part(per_part, pivot),
            }
            if pivot
            else None
        ),
        "layers": [
            {"name": p["name"], "file": p["file"], "z": i}
            for i, p in enumerate(per_part)
        ],
        "parts": per_part,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "output_dir": str(out_dir.resolve()),
        "count": len(paths),
        "canvas_w": int(canvas_w),
        "canvas_h": int(canvas_h),
        "pivot_x": pivot_x,
        "pivot_y": pivot_y,
        "paths": paths,
        "manifest_path": str(manifest_path.resolve()),
        "per_part": per_part,
    }


def _pivot_part(per_part: list[dict], pivot: tuple[int, int] | None) -> str | None:
    """pivot 落在哪个部件的区域内（后者优先，即列表越靠后 z 序越高）。"""
    if not pivot:
        return None
    x, y = pivot
    for p in reversed(per_part):
        x1, y1, x2, y2 = p["rect"]
        if x1 <= x < x2 and y1 <= y < y2:
            return p["name"]
    return None
