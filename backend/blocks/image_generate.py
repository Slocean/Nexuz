"""AI 生图：调用 OpenAI 兼容 /images/generations 端点生成图片并存盘。

端点与密钥在 设置 → Nexuz AI → 生图模型 配置；Base URL / API Key 留空时
自动沿用聊天模型的服务商配置，仅需单独填写生图模型 ID。
响应同时兼容 URL 与 Base64 两种返回格式。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from time import strftime
from typing import Any

import httpx

from backend.core.ai.config import resolve_image_config

SCHEMA = {
    "type": "image_generate",
    "label": "AI 生图",
    "category": "识别类",
    "done_log": "已生成{{count}}张图片：{{first_path}}",
    "inputs": [
        {
            "name": "prompt",
            "type": "string",
            "label": "提示词",
            "default": "",
            "placeholder": "描述画面主体/风格/构图/背景，如：一只橙色小猫，扁平插画风格，居中构图，白色背景",
            "ui": "textarea",
            "bindable": True,
            "required": True,
        },
        {
            "name": "style_preset",
            "type": "select",
            "label": "风格后缀",
            "options": ["none", "transparent_sprite", "game_icon", "detail_enhance"],
            "default": "none",
            "option_labels": {
                "none": "不追加",
                "transparent_sprite": "素材图（纯色背景，便于抠图）",
                "game_icon": "游戏图标",
                "detail_enhance": "细节增强",
            },
        },
        {
            "name": "size",
            "type": "select",
            "label": "尺寸",
            "options": ["auto", "1024x1024", "1024x1792", "1792x1024", "custom"],
            "default": "auto",
            "option_labels": {
                "auto": "模型默认",
                "1024x1024": "1:1（1024×1024）",
                "1024x1792": "竖版 9:16（1024×1792）",
                "1792x1024": "横版 16:9（1792×1024）",
                "custom": "自定义宽高",
            },
        },
        {
            "name": "custom_width",
            "type": "number",
            "label": "宽",
            "default": 1024,
            "show_when": {"size": "custom"},
        },
        {
            "name": "custom_height",
            "type": "number",
            "label": "高",
            "default": 1024,
            "show_when": {"size": "custom"},
        },
        {
            "name": "count",
            "type": "number",
            "label": "生成张数",
            "default": 1,
            "placeholder": "1-4",
        },
        {
            "name": "negative_prompt",
            "type": "string",
            "label": "反向提示词",
            "default": "",
            "placeholder": "不想出现的元素；仅 SD 系厂商（硅基流动等）支持，留空不传",
            "ui": "textarea",
            "bindable": True,
        },
        {
            "name": "seed",
            "type": "number",
            "label": "种子",
            "placeholder": "留空=随机；部分模型支持固定种子复现",
        },
        {
            "name": "extra_params",
            "type": "string",
            "label": "额外参数(JSON)",
            "default": "",
            "placeholder": '{"steps": 30}，合并进请求体，适配厂商私有参数',
            "ui": "textarea",
            "bindable": True,
        },
        {
            "name": "save_path",
            "type": "string",
            "label": "保存路径",
            "default": "",
            "placeholder": "留空则自动保存到数据目录/generated",
            "ui": "file_or_dir",
        },
        {
            "name": "timeout_s",
            "type": "number",
            "label": "超时秒数",
            "default": 120,
            "placeholder": "生图较慢，建议 ≥60",
        },
    ],
    "outputs": [
        {"name": "first_path", "type": "string"},
        {"name": "paths", "type": "array"},
        {"name": "count", "type": "number"},
        {"name": "prompt", "type": "string"},
    ],
}

# 风格后缀：拼接在用户 prompt 之后，与动态绑定的 prompt 可组合。
STYLE_SUFFIXES: dict[str, str] = {
    "none": "",
    "transparent_sprite": "白色纯色背景，单一主体完整居中，无阴影，边缘干净利落，游戏素材图",
    "game_icon": "游戏图标设计，居中构图，色彩鲜明，细节丰富，光影精美",
    "detail_enhance": "高细节，高清画质，专业光影，精美材质质感",
}

_SIZE_PRESETS = {"1024x1024", "1024x1792", "1792x1024"}
_MAX_COUNT = 4


def _images_url(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise ValueError("生图 Base URL 为空，请在设置中填写或让聊天模型配置保持有效")
    if url.endswith("/images/generations"):
        return url
    return f"{url}/images/generations"


def _build_body(params: dict[str, Any], model: str) -> dict[str, Any]:
    prompt = str(params.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("提示词不能为空")
    suffix = STYLE_SUFFIXES.get(str(params.get("style_preset") or "none"), "")
    final_prompt = f"{prompt}，{suffix}" if suffix else prompt

    body: dict[str, Any] = {"model": model, "prompt": final_prompt}

    size = str(params.get("size") or "auto")
    if size == "custom":
        width = int(float(params.get("custom_width") or 0))
        height = int(float(params.get("custom_height") or 0))
        if width <= 0 or height <= 0:
            raise ValueError("自定义尺寸需要填写有效的宽和高")
        body["size"] = f"{width}x{height}"
    elif size in _SIZE_PRESETS:
        body["size"] = size

    try:
        count = int(float(params.get("count") or 1))
    except (TypeError, ValueError):
        count = 1
    count = max(1, min(_MAX_COUNT, count))
    body["n"] = count

    negative = str(params.get("negative_prompt") or "").strip()
    if negative:
        body["negative_prompt"] = negative

    raw_seed = params.get("seed")
    if raw_seed not in (None, ""):
        try:
            body["seed"] = int(float(raw_seed))
        except (TypeError, ValueError):
            pass

    raw_extra = str(params.get("extra_params") or "").strip()
    if raw_extra:
        try:
            extra = json.loads(raw_extra)
        except json.JSONDecodeError as exc:
            raise ValueError(f"额外参数不是合法 JSON：{exc}") from exc
        if not isinstance(extra, dict):
            raise ValueError("额外参数必须是 JSON 对象，如 {\"steps\": 30}")
        body.update(extra)
        body["model"] = model
        body["prompt"] = final_prompt

    return body


def _parse_error_message(status_code: int, payload: dict[str, Any] | None) -> str:
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str):
            return err
        if payload.get("message"):
            return str(payload["message"])
    return f"HTTP {status_code}"


def _request_images(
    url: str, headers: dict[str, str], body: dict[str, Any], timeout_s: float
) -> dict[str, Any]:
    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=timeout_s)
    except httpx.HTTPError as exc:
        raise ValueError(f"生图请求失败：{exc}") from exc
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    if resp.status_code != 200:
        raise ValueError(
            f"生图失败（{_parse_error_message(resp.status_code, payload)}）"
        )
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("生图响应格式异常：缺少 data 数组")
    return payload


def _download_bytes(url: str, timeout_s: float) -> bytes:
    try:
        resp = httpx.get(url, timeout=timeout_s)
    except httpx.HTTPError as exc:
        raise ValueError(f"下载生成图片失败：{exc}") from exc
    if resp.status_code != 200:
        raise ValueError(f"下载生成图片失败：HTTP {resp.status_code}")
    return resp.content


def _resolve_output_target(save_path: str, index: int, total: int) -> Path:
    raw = str(save_path or "").strip()
    if raw:
        out = Path(raw)
        if out.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            out = out if total == 1 else out.with_stem(f"{out.stem}_{index + 1}")
        else:
            out = out / f"gen_{index + 1}.png"
    else:
        from backend.paths import get_data_dir

        out = get_data_dir(create=True) / "generated" / f"gen_{index + 1}.png"
    if out.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        out = out.with_suffix(".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def handler(params, context, **kwargs):
    image_cfg = resolve_image_config()
    body = _build_body(params, image_cfg["model"])

    headers = {"Content-Type": "application/json"}
    if image_cfg["api_key"]:
        headers["Authorization"] = f"Bearer {image_cfg['api_key']}"

    try:
        timeout_s = float(params.get("timeout_s") or 120)
    except (TypeError, ValueError):
        timeout_s = 120.0
    timeout_s = max(10.0, timeout_s)

    payload = _request_images(_images_url(image_cfg["base_url"]), headers, body, timeout_s)

    expected = int(body.get("n") or 1)
    items = [it for it in payload["data"] if isinstance(it, dict)]
    if not items:
        raise ValueError("生图接口未返回任何图片")

    save_path = str(params.get("save_path") or "")
    paths: list[str] = []
    for i, item in enumerate(items):
        out = _resolve_output_target(save_path, i, expected)
        if item.get("b64_json"):
            out.write_bytes(base64.b64decode(str(item["b64_json"])))
        elif item.get("url"):
            out.write_bytes(_download_bytes(str(item["url"]), timeout_s))
        else:
            raise ValueError(f"第{i + 1}张图片响应中既无 b64_json 也无 url 字段")
        paths.append(str(out.resolve()))

    return {
        "first_path": paths[0],
        "paths": paths,
        "count": len(paths),
        "prompt": body["prompt"],
    }
