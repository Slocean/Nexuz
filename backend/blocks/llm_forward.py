"""llm_forward：HTTP 转发积木——借 Nexuz 后台发请求，绕开浏览器跨域限制。

网页直连 LLM 等 API 会被 CORS 拦截；本积木在本机后台代发同一请求，原样送达、
原样带回。它不是对话积木：payload 就是完整的请求体 JSON，积木不解析、不包装、
不丢字段（含各家扩展参数），响应原文返回。

分两种模式（mode 只控制画布字段显隐，handler 共用）：

- 简易模式：Base URL + API Key + 请求体，端点路径与认证头自动拼
  （请求体含 messages → /chat/completions，含 input → /responses）；
- 手动模式：额外露出模型补齐、格式转换（chat↔responses）、额外请求头、超时。

Base URL / API Key / 模型留空时自动沿用「设置 → Nexuz AI」的服务商配置。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from backend.blocks import _llm_formats as core
from backend.core.ai.config import get_ai_config

SCHEMA = {
    "type": "llm_forward",
    "description": "HTTP 转发：借后台代发请求绕开跨域，payload 为完整请求体 JSON，原样送达原样带回，不解析不包装。",
    "label": "LLM 转发",
    "category": "系统类",
    "inputs": [
        {
            "name": "mode",
            "type": "select",
            "label": "模式",
            "options": ["simple", "custom"],
            "default": "simple",
            "option_labels": {"simple": "简易模式（填 Base URL 和 Key 即用）", "custom": "手动模式（全部参数）"},
        },
        {
            "name": "payload",
            "type": "string",
            "label": "请求体 JSON",
            "default": "",
            "ui": "textarea",
            "bindable": True,
            "placeholder": '完整请求体，如 {"model":"gpt-4o","messages":[…]} 或 {"model":…,"input":[…]}',
        },
        {
            "name": "base_url",
            "type": "string",
            "label": "Base URL",
            "default": "",
            "placeholder": "如 https://api.deepseek.com/v1（留空用 Nexuz AI 设置）",
            "ui": "textarea",
            "bindable": True,
        },
        {
            "name": "api_key",
            "type": "string",
            "label": "API Key",
            "default": "",
            "placeholder": "留空用 Nexuz AI 设置里的密钥",
            "bindable": True,
        },
        {
            "name": "model",
            "type": "string",
            "label": "模型",
            "default": "",
            "placeholder": "留空用 payload 自带或 Nexuz AI 设置里的模型",
            "bindable": True,
            "show_when": {"mode": "custom"},
        },
        {
            "name": "convert",
            "type": "select",
            "label": "格式转换",
            "options": ["none", "chat_to_responses", "responses_to_chat"],
            "default": "none",
            "option_labels": {
                "none": "不转换（按原格式直发）",
                "chat_to_responses": "chat → responses",
                "responses_to_chat": "responses → chat",
            },
            "show_when": {"mode": "custom"},
        },
        {
            "name": "headers",
            "type": "keymap",
            "label": "额外请求头",
            "default": {},
            "ui": "input_map",
            "show_when": {"mode": "custom"},
        },
        {
            "name": "timeout_sec",
            "type": "number",
            "label": "超时秒数",
            "default": 120,
            "show_when": {"mode": "custom"},
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "status", "type": "number"},
        {"name": "text", "type": "string"},
        {"name": "response", "type": "object"},
        {"name": "response_json", "type": "string", "canvas": False},
        {"name": "error", "type": "string"},
        {"name": "headers", "type": "object", "canvas": False},
    ],
}

_CHAT_PATH = "/chat/completions"
_RESPONSES_PATH = "/responses"


def _clamp_timeout(raw: Any) -> float:
    try:
        timeout = float(raw if raw not in (None, "") else 120)
    except (TypeError, ValueError):
        timeout = 120.0
    return max(1.0, min(300.0, timeout))


def _normalize_headers(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        key = str(k or "").strip()
        if not key:
            continue
        out[key] = "" if v is None else str(v)
    return out


def _endpoint_url(base_url: str, fmt: str) -> str:
    """base_url + 对应端点路径；已带完整端点路径的 URL 原样使用。"""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("Base URL 为空：请填写或先在 设置 → Nexuz AI 配置服务商")
    if base.endswith(_CHAT_PATH) or base.endswith(_RESPONSES_PATH):
        return base
    suffix = _CHAT_PATH if fmt == core.CHAT else _RESPONSES_PATH
    return f"{base}{suffix}"


def handler(params, context, **kwargs):
    del context
    raw = params.get("payload")
    if raw in (None, ""):
        return _fail("请求体为空", 0)
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return _fail(f"JSON 解析失败：{exc}", 0)
    else:
        payload = raw
    if not isinstance(payload, dict):
        return _fail("请求体必须是 JSON 对象", 0)

    fmt = core.detect_request_format(payload)
    if fmt == core.UNKNOWN:
        return _fail("无法识别请求体格式：需包含 messages 或 input 字段", 0)

    convert = str(params.get("convert") or "none").strip().lower()
    try:
        if convert == "chat_to_responses":
            wire = core.convert(payload, source=core.CHAT, target=core.RESPONSES, kind="request")
            wire_fmt = core.RESPONSES
        elif convert == "responses_to_chat":
            wire = core.convert(payload, source=core.RESPONSES, target=core.CHAT, kind="request")
            wire_fmt = core.CHAT
        elif convert == "none":
            wire, wire_fmt = payload, fmt
        else:
            return _fail(f"未知转换方向：{convert}", 0)
    except ValueError as exc:
        return _fail(f"请求转换失败：{exc}", 0)

    # 模型补齐：参数 > payload 自带 > 设置里的模型（仅 chat）
    model = str(params.get("model") or "").strip()
    if model:
        wire = dict(wire)
        wire["model"] = model
    elif "model" not in wire or not str(wire.get("model") or "").strip():
        cfg = get_ai_config()
        cfg_model = (cfg.model or "").strip() if fmt == core.CHAT else ""
        if cfg_model:
            wire = dict(wire)
            wire["model"] = cfg_model

    # 端点与认证：参数留空自动沿用 Nexuz AI 设置（与生图节点同套路）
    try:
        base_url = str(params.get("base_url") or "").strip()
        api_key = str(params.get("api_key") or "").strip()
        if not base_url or not api_key:
            cfg = get_ai_config()
            base_url = base_url or (cfg.base_url or "").strip()
            api_key = api_key or (cfg.api_key or "").strip()
        endpoint = _endpoint_url(base_url, wire_fmt)
    except ValueError as exc:
        return _fail(str(exc), 0)

    headers = _normalize_headers(params.get("headers"))
    if api_key:
        headers.setdefault("Authorization", f"Bearer {api_key}")
    headers.setdefault("Content-Type", "application/json; charset=utf-8")

    data = json.dumps(wire, ensure_ascii=False).encode("utf-8")
    timeout = _clamp_timeout(params.get("timeout_sec"))
    req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", None) or resp.getcode() or 0)
            raw_body = resp.read()
            resp_headers = {k: v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        raw_body = b""
        try:
            raw_body = exc.read() or b""
        except Exception:
            pass
        resp_headers = dict(exc.headers.items()) if exc.headers else {}
        return _fail(f"HTTP {exc.code}: {exc.reason}", int(exc.code or 0), raw_body, resp_headers)
    except Exception as exc:
        return _fail(str(exc), 0)

    body = raw_body.decode("utf-8", errors="replace")
    try:
        result = json.loads(body)
    except json.JSONDecodeError:
        result = None
    if not isinstance(result, dict):
        # 转发积木只服务 JSON API；非 JSON 响应带原文进 error 供排查。
        return _fail(f"响应不是 JSON：{body[:500]}", status, raw_body, resp_headers)

    if wire_fmt != fmt:
        # 端点按出口格式应答，转回入口格式再交给调用方。
        try:
            result = core.convert(result, source=wire_fmt, target=fmt, kind="response")
        except ValueError as exc:
            return _fail(f"响应转换失败：{exc}", status, raw_body, resp_headers)

    ok = 200 <= status < 300
    return {
        "ok": ok,
        "status": status,
        "text": core.extract_response_text(result),
        "response": result,
        "response_json": json.dumps(result, ensure_ascii=False),
        "error": "" if ok else f"HTTP {status}",
        "headers": resp_headers,
    }


def _fail(err: str, status: int = 0, raw_body: bytes = b"", headers: dict | None = None):
    body_text = raw_body.decode("utf-8", errors="replace") if raw_body else ""
    parsed = None
    if body_text:
        try:
            data = json.loads(body_text)
            if isinstance(data, dict):
                parsed = data
        except json.JSONDecodeError:
            parsed = None
    return {
        "ok": False,
        "status": status,
        "text": "",
        "response": parsed,
        "response_json": body_text,
        "error": err,
        "headers": headers or {},
    }
