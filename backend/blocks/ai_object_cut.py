"""AI 抠主图：视觉模型定位画面中的杂质元素（关闭按钮/水印等），擦除后只保留最大主体。

流程：alpha 前景提取 → 多模态模型按描述定位要去除的元素（返回包围盒，
与图像边缘连通的杂质也能定位，纯几何方法无解）→ 擦除盒内前景像素
（外扩吞掉描边抗锯齿，只动前景、不碰真透明背景）→ 可选 TELEA 修补
补洞 → 连通域取最大主体 → 不规则形状裁切导出透明 PNG。
批量多图逐张处理，单张失败不中断。
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import cv2
import httpx
import numpy as np

from backend.blocks._helpers import (
    common_parent_dir,
    expand_image_sources,
    split_input_paths,
)
from backend.blocks.image_rename import _parse_error_message
from backend.blocks.transparent_cut import (
    IMAGE_EXTS,
    _components_boxes,
    _cut_transparent,
    _fg_mask,
    _resolve_output_root,
)
from backend.core.ai import llm_cache
from backend.core.ai.config import get_ai_config

SCHEMA = {
    "type": "ai_object_cut",
    "label": "AI 抠主图（去杂质）",
    "category": "识别类",
    "done_log": "已成功处理{{sheets}}个文件，共擦除{{removed}}处杂质，总输出{{count}}张主图，输出目录：{{output_dir}}",
    "inputs": [
        {
            "name": "image_path",
            "type": "string",
            "label": "图片路径/文件夹",
            "default": "",
            "placeholder": "PNG 等带透明通道的图片，或文件夹（批量）；支持多选文件，一行一个",
            "ui": "file_or_dir",
            "accept": "*.png;*.webp;*.bmp",
            "bindable": True,
        },
        {
            "name": "output_dir",
            "type": "string",
            "label": "输出目录",
            "default": "",
            "placeholder": "留空则输出到输入旁的 图名_cut/ 文件夹",
            "ui": "file_or_dir",
        },
        {
            "name": "remove_desc",
            "type": "string",
            "label": "要去除的元素描述",
            "default": "",
            "placeholder": "如：右上角的红色圆形关闭按钮；描述带上位置+外观更准",
            "ui": "textarea",
            "bindable": True,
        },
        {
            "name": "inpaint",
            "type": "select",
            "label": "擦除后补洞",
            "options": ["true", "false"],
            "default": "true",
            "option_labels": {"true": "修补缺口（推荐）", "false": "保留透明缺口"},
            "placeholder": "用周边像素修补杂质擦除后留下的缺口（修补处为估算内容）",
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
            "default": 0,
            "placeholder": "软化主体边缘，0=保留原始 alpha",
        },
        {
            "name": "timeout_s",
            "type": "number",
            "label": "AI 超时秒数",
            "default": 90,
            "placeholder": "单张图片的视觉定位请求超时",
        },
        {
            "name": "name_prefix",
            "type": "string",
            "label": "命名前缀",
            "default": "",
            "placeholder": "留空用图片名，如 图名_main.png",
        },
    ],
    "outputs": [
        {"name": "output_dir", "type": "string"},
        {"name": "count", "type": "number"},
        {"name": "removed", "type": "number"},
        {"name": "paths", "type": "object"},
        {"name": "sheets", "type": "number"},
        {"name": "per_file", "type": "object"},
        {"name": "errors", "type": "object"},
    ],
}

# 视觉模型输入的最长边（等比缩小，坐标按比例映射回原图）
_MAX_SIDE = 1024
# 擦除区外扩：吞掉目标描边的抗锯齿残边（像素）
_ERASE_MARGIN = 2


def handler(params, context, **kwargs):
    sources = split_input_paths(params.get("image_path"))
    if not sources:
        raise ValueError("请指定 image_path 图片路径（支持文件或文件夹，可多选）")
    for src in sources:
        if not src.exists():
            raise FileNotFoundError(f"路径不存在: {src}")

    if len(sources) == 1:
        src = sources[0]
        if src.is_dir():
            return _run_batch(src, params)
        return _run_single(src, params)
    return _run_multi(sources, params)


def _resolve_ai_cfg(params) -> tuple[dict[str, str], float]:
    """读取聊天模型配置；未配置时给出与 图片批量重命名 一致的提示。"""
    cfg = get_ai_config()
    base_url = str(cfg.base_url or "").strip()
    model = str(cfg.model or "").strip()
    if not base_url or not model:
        raise ValueError(
            "未配置聊天模型：请在 设置 → Nexuz AI 填写 Base URL 与模型 ID"
            "（需支持图像输入的多模态模型，如 gpt-4o / qwen-vl / glm-4v）"
        )
    timeout_raw = params.get("timeout_s")
    timeout_s = max(10.0, float(timeout_raw if timeout_raw is not None else 90))
    return (
        {
            "base_url": base_url,
            "api_key": str(cfg.api_key or "").strip(),
            "model": model,
        },
        timeout_s,
    )


def _scaled_jpeg_b64(data: np.ndarray) -> tuple[str, float, tuple[int, int]]:
    """前景按白底合成后压成 JPEG Base64（视觉模型输入），返回 (b64, 缩放比, 缩放后宽高)。"""
    h, w = data.shape[:2]
    scale = min(1.0, _MAX_SIDE / max(h, w))
    rgb = data[:, :, :3].astype(np.float32)
    af = (data[:, :, 3].astype(np.float32) / 255.0)[:, :, None]
    comp = (rgb * af + 255.0 * (1.0 - af)).astype(np.uint8)
    if scale < 1.0:
        comp = cv2.resize(
            comp,
            (max(1, round(w * scale)), max(1, round(h * scale))),
            interpolation=cv2.INTER_AREA,
        )
    ok, buf = cv2.imencode(".jpg", comp, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        raise ValueError("视觉模型输入图编码失败")
    return (
        base64.b64encode(buf.tobytes()).decode("ascii"),
        scale,
        (int(comp.shape[1]), int(comp.shape[0])),
    )


def _ai_locate(
    b64: str,
    scaled_wh: tuple[int, int],
    ai_cfg: dict[str, str],
    remove_desc: str,
    timeout_s: float,
    image_sha: str = "",
) -> str:
    """调用视觉模型返回定位 JSON 原文；同图同描述同模型命中缓存直接复用。"""
    sw, sh = scaled_wh
    prompt = (
        f"这是一张图片，尺寸 {sw}x{sh} 像素，坐标原点在左上角，x 向右 y 向下。\n"
        f"请找出图中所有符合以下描述的元素（重复出现的实例一个不漏）：\n"
        f"「{remove_desc}」\n"
        "只输出 JSON，不要任何其他文字：\n"
        '{"targets": [{"label": "元素简述", "bbox": [x1, y1, x2, y2]}]}\n'
        "要求：bbox 紧贴元素边缘（含描边），为该尺寸图上的整数像素坐标；"
        '找不到任何匹配元素时输出 {"targets": []}。'
    )
    cache_key = ""
    if llm_cache.enabled():
        try:
            cache_key = llm_cache.make_key(
                purpose="ai_object_cut",
                model=str(ai_cfg.get("model") or ""),
                base_url=str(ai_cfg.get("base_url") or ""),
                temperature=0.0,
                extra={"prompt": prompt, "image_sha": image_sha},
            )
        except Exception:
            cache_key = ""
        if cache_key:
            hit = llm_cache.get_json(cache_key)
            if isinstance(hit, str) and hit:
                return hit

    url = ai_cfg["base_url"].rstrip("/")
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if ai_cfg["api_key"]:
        headers["Authorization"] = f"Bearer {ai_cfg['api_key']}"
    body = {
        "model": ai_cfg["model"],
        "temperature": 0.0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            }
        ],
    }
    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=timeout_s)
    except httpx.HTTPError as exc:
        raise ValueError(f"AI 定位请求失败: {exc}") from exc
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    if resp.status_code != 200:
        raise ValueError(
            f"AI 定位失败（{_parse_error_message(resp.status_code, payload)}）"
        )
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("AI 定位响应格式异常：缺少 choices[0].message.content") from exc
    content = str(content or "")
    if cache_key and content:
        llm_cache.put_json(cache_key, content)
    return content


def _parse_targets(content: str) -> list[tuple[int, int, int, int]]:
    """从模型回复提取 targets 包围盒（宽松解析：剥代码围栏、截取首个 JSON 对象）。"""
    text = (content or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("AI 定位返回格式异常：未找到 JSON 对象")
    try:
        obj, _end = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise ValueError(f"AI 定位返回格式异常：JSON 解析失败（{exc}）") from exc
    targets = obj.get("targets") if isinstance(obj, dict) else None
    if targets is None:
        raise ValueError("AI 定位返回格式异常：缺少 targets 数组")
    boxes: list[tuple[int, int, int, int]] = []
    for t in targets if isinstance(targets, list) else []:
        if not isinstance(t, dict):
            continue
        bbox = t.get("bbox")
        if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
            continue
        try:
            x1, y1, x2, y2 = (float(v) for v in bbox)
        except (TypeError, ValueError):
            continue
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        if x2 - x1 < 1 or y2 - y1 < 1:
            continue
        boxes.append((round(x1), round(y1), round(x2), round(y2)))
    return boxes


def _erase_targets(
    data: np.ndarray, boxes: list[tuple[int, int, int, int]]
) -> tuple[np.ndarray, np.ndarray]:
    """擦除包围盒内的前景像素，返回 (新 BGRA, 擦除掩码)。

    盒子外扩 _ERASE_MARGIN 吞掉目标描边的抗锯齿残边；膨胀与擦除都
    限定在前景内，绝不触碰原本就透明的背景像素。
    """
    h, w = data.shape[:2]
    fg = data[:, :, 3] > 0
    core = np.zeros((h, w), dtype=bool)
    for (x1, y1, x2, y2) in boxes:
        xa, ya = max(0, x1 - _ERASE_MARGIN), max(0, y1 - _ERASE_MARGIN)
        xb, yb = min(w, x2 + _ERASE_MARGIN), min(h, y2 + _ERASE_MARGIN)
        if xb <= xa or yb <= ya:
            continue
        core[ya:yb, xa:xb] |= fg[ya:yb, xa:xb]
    if not core.any():
        return data, core
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    erased = cv2.dilate(core.astype(np.uint8), kernel).astype(bool) & fg
    alpha = data[:, :, 3].copy()
    alpha[erased] = 0
    return np.dstack([data[:, :, :3], alpha]), erased


def _inpaint_holes(data: np.ndarray, holes: np.ndarray) -> np.ndarray:
    """TELEA 修补擦除留下的缺口。

    只补「完全被剩余前景包围」的擦除缺口（内部水印、贴纸等）——按
    alpha 零区的连通性判定，与外部背景连通的缺口（例如按钮超出面板
    轮廓的部分）保持透明，避免修补让主图长出伪造的凸块。透明区按白
    底合成后修补，只把待补像素写回为不透明；主体自带的真透明孔洞
    （非本次擦除产生）不受影响。
    """
    if not holes.any():
        return data
    alpha = data[:, :, 3]
    zero = alpha == 0
    _n, labels = cv2.connectedComponents(zero.astype(np.uint8), connectivity=4)
    h, w = labels.shape
    border = np.unique(
        np.concatenate([labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]])
    )
    enclosed = zero & ~np.isin(labels, border)  # 边缘零区全部视为与外部连通
    fill = enclosed & holes
    if not fill.any():
        return data

    rgb = data[:, :, :3].astype(np.float32)
    af = (alpha.astype(np.float32) / 255.0)[:, :, None]
    comp = (rgb * af + 255.0 * (1.0 - af)).astype(np.uint8)
    mask = cv2.dilate(fill.astype(np.uint8) * 255, np.ones((3, 3), np.uint8))
    filled = cv2.inpaint(comp, mask, 3, cv2.INPAINT_TELEA)
    out = data.copy()
    out[:, :, :3][fill] = filled[fill]
    out[:, :, 3][fill] = 255
    return out


def _cut_main(
    data: np.ndarray, padding: int, feather: int
) -> np.ndarray:
    """擦除后取最大连通域主体，按不规则形状裁切，返回 BGRA。"""
    fg = _fg_mask(data[:, :, 3], 30)
    if not fg.any():
        raise ValueError("擦除后没有剩余前景，无法保留主图")
    boxes, labels, _total = _components_boxes(fg, 0)
    main = max(boxes, key=lambda b: b[4])
    return _cut_transparent(
        data, main, padding=padding, feather=feather, labels=labels
    )


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
    if not (data.ndim == 3 and data.shape[2] == 4):
        raise ValueError(
            f"图片没有 Alpha 通道: {src}"
            "（白底/棋盘格假透明图请先在 透明图自动切割 中用「浅色底自动抠除」去底，"
            "或使用带透明通道的图片）"
        )

    remove_desc = str(params.get("remove_desc") or "").strip()
    if not remove_desc:
        raise ValueError(
            "请填写要去除的元素描述 remove_desc，如：右上角的红色圆形关闭按钮"
        )

    ai_cfg, timeout_s = _resolve_ai_cfg(params)
    b64, scale, scaled_wh = _scaled_jpeg_b64(data)
    content = _ai_locate(
        b64,
        scaled_wh,
        ai_cfg,
        remove_desc,
        timeout_s,
        image_sha=llm_cache.sha256_bytes(raw.tobytes()),
    )
    targets = _parse_targets(content)
    h, w = data.shape[:2]
    boxes = [
        (
            max(0, min(w - 1, int(round(x1 / scale)))),
            max(0, min(h - 1, int(round(y1 / scale)))),
            max(1, min(w, int(round(x2 / scale)))),
            max(1, min(h, int(round(y2 / scale)))),
        )
        for (x1, y1, x2, y2) in targets
    ]
    if not boxes:
        raise ValueError(
            f"AI 未在图中定位到要去除的目标（描述：{remove_desc}）。"
            "请换更具体的位置+外观描述，并确认使用支持图像输入的多模态模型"
        )

    inpaint = str(params.get("inpaint") or "true").strip().lower() == "true"
    data, holes = _erase_targets(data, boxes)
    erased_px = int(holes.sum())
    if inpaint and erased_px:
        data = _inpaint_holes(data, holes)

    padding = max(0, int(params.get("padding") if params.get("padding") is not None else 0))
    feather = max(0, int(params.get("feather") if params.get("feather") is not None else 0))
    crop = _cut_main(data, padding, feather)

    prefix = str(params.get("name_prefix") or "").strip()
    out_path = out_dir if out_dir is not None else _resolve_output_root(params, src)
    out_path.mkdir(parents=True, exist_ok=True)
    name = f"{prefix or src.stem}_main.png"
    target = out_path / name
    ok, buf = cv2.imencode(".png", crop)
    if not ok:
        raise ValueError(f"PNG 编码失败: {target}")
    buf.tofile(str(target))

    return {
        "output_dir": str(out_path.resolve()),
        "count": 1,
        "removed": len(boxes),
        "paths": [str(target.resolve())],
        "sheets": 1,
        "per_file": [
            {
                "image": str(src.resolve()),
                "output_dir": str(out_path.resolve()),
                "count": 1,
                "removed": len(boxes),
                "erased_px": erased_px,
                "path": str(target.resolve()),
            }
        ],
        "errors": [],
    }


def _run_batch(folder: Path, params) -> dict:
    """文件夹批量模式：扫描文件夹内所有图片逐张处理，单张失败不中断整体。"""
    files = sorted(
        p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    if not files:
        raise ValueError(
            f"文件夹中未找到图片（支持 {'、'.join(sorted(IMAGE_EXTS))}）: {folder}"
        )
    return _run_files(files, params, _resolve_output_root(params, folder))


def _run_multi(sources: list[Path], params) -> dict:
    """多来源批量模式：多选文件/文件夹混合，逐张处理，单张失败不中断整体。"""
    files = expand_image_sources(sources, IMAGE_EXTS)
    out_root = _resolve_output_root(params, common_parent_dir(files))
    return _run_files(files, params, out_root)


def _run_files(files: list[Path], params, out_root: Path) -> dict:
    """对给定图片列表逐张处理并聚合结果。"""
    out_root.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    per_file: list[dict] = []
    errors: list[dict] = []
    total = 0
    removed = 0
    for f in files:
        try:
            res = _run_single(f, params, out_dir=out_root / f.stem)
        except Exception as exc:  # noqa: BLE001 — 单张失败不中断批量
            errors.append({"image": str(f), "error": str(exc)})
            continue
        total += int(res["count"])
        removed += int(res["removed"])
        paths.extend(res["paths"])
        per_file.extend(res["per_file"])

    return {
        "output_dir": str(out_root.resolve()),
        "count": total,
        "removed": removed,
        "paths": paths,
        "sheets": len(files),
        "per_file": per_file,
        "errors": errors,
    }
