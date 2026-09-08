"""样式审计：对截图/贴图做确定性测量（文字贴边/超出、互相遮挡、对比度、主色提取）。

定位（docs/style_audit.md）：工具负责测量和取证，结论由调用方 AI 复核。
输出「问题类型 + 坐标 + 数字证据 + 置信度（severity）」，不做 VLM 调用。

典型链路（MCP / AI 会话）：
  screenshot（输出 path）→ style_audit（image_path 绑定该 path）→ 复核 issues 与标注图。
"""

from __future__ import annotations

import json

from backend.blocks import _style_audit as core

SCHEMA = {
    "type": "style_audit",
    "description": "对截图做确定性样式测量：文字贴边/超出画布、互相遮挡、WCAG 对比度、主色提取。",
    "label": "样式审计",
    "category": "识别类",
    "done_log": "样式审计完成：{{text_count}} 个文字框，{{issue_count}} 个疑似问题",
    "inputs": [
        {
            "name": "image_path",
            "type": "string",
            "label": "图片路径",
            "default": "",
            "placeholder": "截图/贴图文件路径，可绑定区域截图的 path",
            "required": True,
            "bindable": True,
        },
        {
            "name": "text_source",
            "type": "select",
            "label": "文字来源",
            "options": ["auto", "custom", "none"],
            "default": "auto",
            "option_labels": {
                "auto": "内置 OCR",
                "custom": "外部词框（text_boxes）",
                "none": "跳过文字检查",
            },
        },
        {
            "name": "text_boxes",
            "type": "string",
            "label": "外部词框 JSON",
            "default": "",
            "placeholder": '[{"text":"开始","left":10,"top":20,"width":60,"height":24}]',
            "ui": "textarea",
            "show_when": {"text_source": "custom"},
        },
        {
            "name": "region",
            "type": "rect",
            "label": "审计区域 [x1,y1,x2,y2]",
            "default": None,
            "placeholder": "留空=整图；填入则只审该区域，报告坐标仍为原图坐标",
        },
        {
            "name": "origin_x",
            "type": "number",
            "label": "原图屏幕X",
            "default": 0,
            "placeholder": "截图区域 left，issues 坐标 = 图内坐标 + 原点",
        },
        {
            "name": "origin_y",
            "type": "number",
            "label": "原图屏幕Y",
            "default": 0,
            "placeholder": "截图区域 top",
        },
        {
            "name": "min_confidence",
            "type": "number",
            "label": "OCR置信度下限",
            "default": 0.3,
            "show_when": {"text_source": "auto"},
        },
        {
            "name": "filter_decor",
            "type": "boolean",
            "label": "过滤装饰纹理误报",
            "default": True,
            "show_when": {"text_source": "auto"},
        },
        {
            "name": "min_text_height",
            "type": "number",
            "label": "最小文字高度(px，0=关)",
            "default": 8,
            "show_when": {"text_source": "auto"},
        },
        {
            "name": "checks",
            "type": "string",
            "label": "启用检查项",
            "default": "edge_clipping,occlusion,low_contrast",
            "placeholder": "逗号分隔；空 = 全部",
        },
        {
            "name": "margin_px",
            "type": "number",
            "label": "贴边容差(px)",
            "default": 2,
        },
        {
            "name": "contrast_threshold",
            "type": "number",
            "label": "对比度阈值",
            "default": 4.5,
            "placeholder": "WCAG 对比度低于该值报 medium，低于 2.5 报 high",
        },
        {
            "name": "palette_size",
            "type": "number",
            "label": "主色数量",
            "default": 6,
            "placeholder": "0 = 跳过配色提取",
        },
        {
            "name": "save_report",
            "type": "string",
            "label": "报告保存路径",
            "default": "",
            "placeholder": "可选，JSON 报告落盘路径",
        },
        {
            "name": "annotate_path",
            "type": "string",
            "label": "标注图保存路径",
            "default": "",
            "placeholder": "可选，问题框标注图落盘路径",
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "issue_count", "type": "number"},
        {"name": "text_count", "type": "number"},
        {"name": "filtered_count", "type": "number"},
        {"name": "issues", "type": "array", "itemType": "object", "canvas": False},
        {"name": "texts", "type": "array", "itemType": "object", "canvas": False},
        {"name": "region", "type": "object", "canvas": False},
        {"name": "palette", "type": "object", "canvas": False},
        {"name": "image", "type": "object", "canvas": False},
        {"name": "report_path", "type": "string"},
        {"name": "annotated_path", "type": "string"},
    ],
}


def _parse_region(value) -> list[int] | None:
    """解析审计区域 [x1,y1,x2,y2]（图内坐标），留空返回 None。"""
    if value is None or value == "":
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"无效 region: {value}（需要 [x1,y1,x2,y2]）")
    try:
        x1, y1, x2, y2 = [int(round(float(v))) for v in value]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"无效 region: {value}") from exc
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"无效区域: {list(value)}")
    return [x1, y1, x2, y2]


def _apply_region(img, region: list[int]):
    """按区域裁剪（越界部分夹回图内），返回 (裁剪图, 实际生效区域)。"""
    width, height = img.size
    x1 = max(0, min(region[0], width - 1))
    y1 = max(0, min(region[1], height - 1))
    x2 = max(x1 + 1, min(region[2], width))
    y2 = max(y1 + 1, min(region[3], height))
    return img.crop((x1, y1, x2, y2)), [x1, y1, x2, y2]


def _as_float(value, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default: int) -> int:
    return int(_as_float(value, default))


def handler(params, context, **kwargs):
    image_path = str(params.get("image_path") or "").strip()
    if not image_path:
        raise ValueError("请设置图片路径（可绑定区域截图的 path）")

    text_source = str(params.get("text_source") or "auto").strip().lower() or "auto"
    if text_source not in ("auto", "custom", "none"):
        text_source = "auto"

    checks = core.parse_checks(params.get("checks"))
    origin_x = _as_int(params.get("origin_x"), 0)
    origin_y = _as_int(params.get("origin_y"), 0)
    margin_px = _as_int(params.get("margin_px"), 2)
    contrast_threshold = _as_float(params.get("contrast_threshold"), 4.5)
    palette_size = _as_int(params.get("palette_size"), 6)
    min_confidence = _as_float(params.get("min_confidence"), 0.3)
    filter_decor = params.get("filter_decor")
    filter_decor = True if filter_decor is None else bool(filter_decor)
    min_text_height = _as_int(params.get("min_text_height"), core._DEFAULT_MIN_TEXT_HEIGHT)

    img = core.load_image(image_path)

    region = _parse_region(params.get("region"))
    crop_rect: list[int] | None = None
    if region:
        img, crop_rect = _apply_region(img, region)

    boxes: list[dict] = []
    ocr_error: str | None = None
    text_checks = [c for c in checks if c != "low_contrast"]
    if text_source == "custom":
        boxes = core.parse_text_boxes(params.get("text_boxes"))
        if not boxes and text_checks:
            raise ValueError("外部词框模式（custom）需要提供有效的 text_boxes JSON 数组")
    elif text_source == "auto":
        try:
            boxes = core.run_text_ocr(img, min_confidence=min_confidence)
        except Exception as exc:
            ocr_error = str(exc)
            # OCR 引擎故障不阻断审计：跳过文字类检查，仍输出配色/报告
            text_checks = []
        else:
            # 文字性预滤：被滤框留在 texts[] 留痕，但不参与文字检查
            if boxes and filter_decor:
                boxes = core.annotate_text_likeness(img, boxes, min_height=min_text_height)
    # text_source == "none"：不取词框

    # 词框缺失时，依赖词框的检查自动失去意义——按无输入处理而非报错
    if not boxes:
        text_checks = []
    effective_checks = [
        c
        for c in checks
        if c == "low_contrast" or (c in text_checks)
    ]

    # region 相对 image_path 原图偏移，叠加用户显式指定的屏幕原点
    origin = (
        origin_x + (crop_rect[0] if crop_rect else 0),
        origin_y + (crop_rect[1] if crop_rect else 0),
    )

    report = core.audit_image(
        img,
        text_boxes=boxes,
        checks=effective_checks,
        margin_px=margin_px,
        contrast_threshold=contrast_threshold,
        palette_size=palette_size,
        origin=origin,
        annotate_path=str(params.get("annotate_path") or "").strip(),
        save_report_path=str(params.get("save_report") or "").strip(),
        ocr_error=ocr_error,
        region=crop_rect,
    )
    report["image"]["path"] = image_path

    return {
        "ok": True,
        "issue_count": int(report.get("issue_count") or 0),
        "text_count": int(report.get("text_count") or 0),
        "filtered_count": int(report.get("filtered_count") or 0),
        "issues": report.get("issues") or [],
        "texts": report.get("texts") or [],
        "region": report.get("region"),
        "palette": report.get("palette") or {},
        "image": report.get("image") or {},
        "report_path": str(report.get("report_path") or ""),
        "annotated_path": str(report.get("annotated_path") or ""),
    }
