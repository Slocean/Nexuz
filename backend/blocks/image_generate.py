"""AI 生图：调用 OpenAI 兼容 /images/generations 端点生成图片并存盘。

端点与密钥在 设置 → Nexuz AI → 生图模型 配置；Base URL / API Key 留空时
自动沿用聊天模型的服务商配置，仅需单独填写生图模型 ID。
响应同时兼容 URL 与 Base64 两种返回格式；URL 模式的图片下载带浏览器式 UA、
跟随重定向，并与 API 请求一样对瞬态网络错误（SSL 断流/连接重置/超时）自动重试。

默认按时间戳自动命名，历史图片不会相互覆盖；也提供固定文件名模式
（覆盖旧图）供需要固定路径的流程使用。模式选"图片编辑（图生图）"时，
以上传的参考图为底进行修改，走 OpenAI 兼容 /images/edits 端点。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from time import strftime
from typing import Any

import httpx

from backend.core.ai import llm_cache
from backend.core.ai.config import resolve_image_config
from backend.core.ai.retry import with_retry

SCHEMA = {
    "type": "image_generate",
    "label": "AI 生图",
    "category": "识别类",
    "done_log": "已生成{{count}}张图片：{{first_path}}",
    "inputs": [
        {
            "name": "mode",
            "type": "select",
            "label": "生成模式",
            "options": ["text2img", "img2img"],
            "default": "text2img",
            "option_labels": {
                "text2img": "文生图",
                "img2img": "图片编辑（图生图）",
            },
        },
        {
            "name": "source_image",
            "type": "string",
            "label": "参考图",
            "default": "",
            "placeholder": "本地图片路径 / URL，可绑定上游输出的图片路径",
            "ui": "file_or_dir",
            "bindable": True,
            "required": True,
            "show_when": {"mode": "img2img"},
        },
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
            "name": "filename_mode",
            "type": "select",
            "label": "文件命名",
            "options": ["timestamp", "fixed"],
            "default": "timestamp",
            "option_labels": {
                "timestamp": "自动命名（时间戳，不覆盖旧图）",
                "fixed": "固定文件名（覆盖旧图）",
            },
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

# 厂商返回的图片托管 CDN 会掐断 python-httpx 默认 UA 的连接，表现为
# SSL UNEXPECTED_EOF / 连接重置；下载统一带浏览器式 UA 并跟随重定向。
_DOWNLOAD_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class _DownloadStatusError(Exception):
    """非 200 下载响应；携带状态码供 with_retry 按 _TRANSIENT_STATUS 判定可重试。"""

    def __init__(self, status_code: int):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def _images_url(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise ValueError("生图 Base URL 为空，请在设置中填写或让聊天模型配置保持有效")
    if url.endswith("/images/generations"):
        return url
    return f"{url}/images/generations"


def _images_edit_url(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise ValueError("生图 Base URL 为空，请在设置中填写或让聊天模型配置保持有效")
    if url.endswith("/images/edits"):
        return url
    return f"{url}/images/edits"


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
    def do_post() -> httpx.Response:
        return httpx.post(url, headers=headers, json=body, timeout=timeout_s)

    try:
        resp = with_retry(do_post, what="生图请求")
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


def _build_edit_form(params: dict[str, Any], model: str) -> dict[str, str]:
    """图片编辑的表单字段（multipart，不含图片文件本体）。"""
    prompt = str(params.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("提示词不能为空")
    suffix = STYLE_SUFFIXES.get(str(params.get("style_preset") or "none"), "")
    final_prompt = f"{prompt}，{suffix}" if suffix else prompt

    form: dict[str, str] = {"model": model, "prompt": final_prompt}

    size = str(params.get("size") or "auto")
    if size == "custom":
        width = int(float(params.get("custom_width") or 0))
        height = int(float(params.get("custom_height") or 0))
        if width <= 0 or height <= 0:
            raise ValueError("自定义尺寸需要填写有效的宽和高")
        form["size"] = f"{width}x{height}"
    elif size in _SIZE_PRESETS:
        form["size"] = size

    try:
        count = int(float(params.get("count") or 1))
    except (TypeError, ValueError):
        count = 1
    form["n"] = str(max(1, min(_MAX_COUNT, count)))

    negative = str(params.get("negative_prompt") or "").strip()
    if negative:
        form["negative_prompt"] = negative

    raw_seed = params.get("seed")
    if raw_seed not in (None, ""):
        try:
            form["seed"] = str(int(float(raw_seed)))
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
        for key, value in extra.items():
            if key in ("model", "prompt"):
                continue
            form[str(key)] = str(value)

    return form


def _request_image_edits(
    url: str,
    headers: dict[str, str],
    form: dict[str, str],
    image: tuple[bytes, str, str],
    timeout_s: float,
) -> dict[str, Any]:
    data, filename, mime = image
    files = {"image": (filename, data, mime)}

    def do_post() -> httpx.Response:
        return httpx.post(url, headers=headers, data=form, files=files, timeout=timeout_s)

    try:
        resp = with_retry(do_post, what="图片编辑请求")
    except httpx.HTTPError as exc:
        raise ValueError(f"图片编辑请求失败：{exc}") from exc
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    if resp.status_code != 200:
        raise ValueError(
            f"图片编辑失败（{_parse_error_message(resp.status_code, payload)}）"
        )
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("图片编辑响应格式异常：缺少 data 数组")
    return payload


def _download_bytes(url: str, timeout_s: float, *, what: str = "生成图片") -> bytes:
    def fetch() -> bytes:
        resp = httpx.get(
            url,
            timeout=timeout_s,
            headers={"User-Agent": _DOWNLOAD_UA},
            follow_redirects=True,
        )
        if resp.status_code != 200:
            raise _DownloadStatusError(resp.status_code)
        return resp.content

    try:
        return with_retry(fetch, what=f"下载{what}")
    except _DownloadStatusError as exc:
        raise ValueError(f"下载{what}失败：HTTP {exc.status_code}") from exc
    except httpx.HTTPError as exc:
        raise ValueError(f"下载{what}失败：{exc}") from exc


_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _load_source_image(source: Any, timeout_s: float) -> tuple[bytes, str, str]:
    """读取参考图，返回 (字节, 文件名, MIME)。

    支持本地路径、http(s) URL、data URL；绑定上游数组时取第一个图片路径。
    """
    if isinstance(source, (list, tuple)):
        source = next(
            (s for s in source if isinstance(s, str) and s.strip()), ""
        )
    raw = str(source or "").strip()
    if not raw:
        raise ValueError("图片编辑模式需要提供参考图")

    if raw.startswith("data:"):
        header, _, b64 = raw.partition(",")
        mime = "image/png"
        if ";" in header:
            mime = header[5:].split(";", 1)[0] or mime
        try:
            return base64.b64decode(b64), "source.png", mime
        except ValueError as exc:
            raise ValueError("data URL 参考图不是合法 Base64") from exc

    if raw.startswith(("http://", "https://")):
        data = _download_bytes(raw, timeout_s, what="参考图")
        name = Path(raw.split("?", 1)[0]).name or "source.png"
        mime = _IMAGE_MIME.get(Path(name).suffix.lower(), "image/png")
        return data, name, mime

    path = Path(raw)
    if not path.is_file():
        raise ValueError(f"参考图不存在：{raw}")
    mime = _IMAGE_MIME.get(path.suffix.lower(), "image/png")
    name = path.name if path.suffix.lower() in _IMAGE_MIME else f"{path.stem}.png"
    try:
        return path.read_bytes(), name, mime
    except OSError as exc:
        raise ValueError(f"读取参考图失败：{exc}") from exc


def _resolve_output_target(
    save_path: str,
    index: int,
    total: int,
    *,
    filename_mode: str = "timestamp",
    timestamp: str | None = None,
) -> Path:
    raw = str(save_path or "").strip()
    ts = timestamp or strftime("%Y%m%d_%H%M%S")
    unique = filename_mode != "fixed"

    def finalize(out: Path) -> Path:
        if out.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            out = out.with_suffix(".png")
        if unique:
            out = _unique_path(out)
        return out

    if raw:
        out = Path(raw)
        if out.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            stem = f"{out.stem}_{ts}" if unique else out.stem
            if total > 1:
                stem = f"{stem}_{index + 1}"
            out = out.with_name(f"{stem}{out.suffix}")
        else:
            base = "gen" if not unique else f"gen_{ts}"
            out = out / f"{base}_{index + 1}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        return finalize(out)

    from backend.paths import get_data_dir

    base = "gen" if not unique else f"gen_{ts}"
    out = get_data_dir(create=True) / "generated" / f"{base}_{index + 1}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    return finalize(out)


def _unique_path(out: Path) -> Path:
    """时间戳秒级仍可能撞名（如循环内连跑），存在时追加序号。"""
    if not out.exists():
        return out
    for n in range(2, 1000):
        cand = out.with_name(f"{out.stem}_{n}{out.suffix}")
        if not cand.exists():
            return cand
    return out


def _cache_payload(keys: list[str], params: dict[str, Any]) -> dict[str, Any] | None:
    """缓存全命中时直接落盘返回（跳过 API 请求）；任一未命中返回 None。"""
    blobs = [llm_cache.get_blob(k) for k in keys]
    if not blobs or any(b is None for b in blobs):
        return None
    timestamp = strftime("%Y%m%d_%H%M%S")
    filename_mode = str(params.get("filename_mode") or "timestamp")
    save_path = str(params.get("save_path") or "")
    paths: list[str] = []
    for i, data in enumerate(blobs):
        out = _resolve_output_target(
            save_path,
            i,
            len(blobs),
            filename_mode=filename_mode,
            timestamp=timestamp,
        )
        out.write_bytes(data)
        paths.append(str(out.resolve()))
    return {
        "first_path": paths[0],
        "paths": paths,
        "count": len(paths),
        "prompt": _final_prompt(params),
        "cached": True,
    }


def handler(params, context, **kwargs):
    image_cfg = resolve_image_config()
    mode = str(params.get("mode") or "text2img")

    headers = {"Content-Type": "application/json"}
    if image_cfg["api_key"]:
        headers["Authorization"] = f"Bearer {image_cfg['api_key']}"

    try:
        timeout_s = float(params.get("timeout_s") or 120)
    except (TypeError, ValueError):
        timeout_s = 120.0
    timeout_s = max(10.0, timeout_s)

    use_cache = llm_cache.enabled()
    cache_keys: list[str] = []

    if mode == "img2img":
        edit_headers = {k: v for k, v in headers.items() if k != "Content-Type"}
        form = _build_edit_form(params, image_cfg["model"])
        image = _load_source_image(params.get("source_image"), timeout_s)
        if use_cache:
            base = llm_cache.make_key(
                purpose="image_generate",
                model=image_cfg["model"],
                base_url=image_cfg["base_url"],
                extra={
                    "mode": "img2img",
                    "form": form,
                    "source_sha": llm_cache.sha256_bytes(image[0]),
                },
            )
            cache_keys = [f"{base}#{i}" for i in range(max(1, int(form.get("n") or 1)))]
            hit = _cache_payload(cache_keys, params)
            if hit is not None:
                return hit
        payload = _request_image_edits(
            _images_edit_url(image_cfg["base_url"]),
            edit_headers,
            form,
            image,
            timeout_s,
        )
    else:
        body = _build_body(params, image_cfg["model"])
        if use_cache:
            base = llm_cache.make_key(
                purpose="image_generate",
                model=image_cfg["model"],
                base_url=image_cfg["base_url"],
                extra={"mode": "text2img", "body": body},
            )
            cache_keys = [f"{base}#{i}" for i in range(max(1, int(body.get("n") or 1)))]
            hit = _cache_payload(cache_keys, params)
            if hit is not None:
                return hit
        payload = _request_images(_images_url(image_cfg["base_url"]), headers, body, timeout_s)

    timestamp = strftime("%Y%m%d_%H%M%S")
    filename_mode = str(params.get("filename_mode") or "timestamp")
    save_path = str(params.get("save_path") or "")
    paths: list[str] = []
    for i, item in enumerate(payload["data"]):
        if not isinstance(item, dict):
            continue
        out = _resolve_output_target(
            save_path,
            i,
            len(payload["data"]),
            filename_mode=filename_mode,
            timestamp=timestamp,
        )
        if item.get("b64_json"):
            data = base64.b64decode(str(item["b64_json"]))
        elif item.get("url"):
            data = _download_bytes(str(item["url"]), timeout_s)
        else:
            raise ValueError(f"第{i + 1}张图片响应中既无 b64_json 也无 url 字段")
        out.write_bytes(data)
        if cache_keys and i < len(cache_keys):
            llm_cache.put_blob(cache_keys[i], data)
        paths.append(str(out.resolve()))

    if not paths:
        raise ValueError("生图接口未返回任何图片")

    return {
        "first_path": paths[0],
        "paths": paths,
        "count": len(paths),
        "prompt": _final_prompt(params),
    }


def _final_prompt(params: dict[str, Any]) -> str:
    prompt = str(params.get("prompt") or "").strip()
    suffix = STYLE_SUFFIXES.get(str(params.get("style_preset") or "none"), "")
    return f"{prompt}，{suffix}" if suffix else prompt
