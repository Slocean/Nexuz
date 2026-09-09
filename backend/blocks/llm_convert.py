"""llm_convert：LLM API 格式转换积木（chat/completions ↔ responses）。

纯转换不发网络；输入可以是 JSON 字符串或对象（对象来自上游积木绑定）。
source/target/kind 都支持 auto 探测，探测口径见 _llm_formats。
"""

from __future__ import annotations

import json

from backend.blocks import _llm_formats as core

SCHEMA = {
    "type": "llm_convert",
    "description": "LLM API 格式转换：chat/completions 与 responses 的请求/响应互转。",
    "label": "LLM 格式转换",
    "category": "系统类",
    "inputs": [
        {
            "name": "payload",
            "type": "string",
            "label": "数据",
            "default": "",
            "ui": "textarea",
            "bindable": True,
            "placeholder": 'JSON 字符串，如 {"model":"gpt-4o","messages":[…]}',
        },
        {
            "name": "source",
            "type": "select",
            "label": "源格式",
            "options": ["auto", "chat", "responses"],
            "default": "auto",
            "option_labels": {"auto": "自动探测", "chat": "chat/completions", "responses": "responses"},
        },
        {
            "name": "target",
            "type": "select",
            "label": "目标格式",
            "options": ["auto", "chat", "responses"],
            "default": "auto",
            "option_labels": {"auto": "与源相同", "chat": "chat/completions", "responses": "responses"},
        },
        {
            "name": "kind",
            "type": "select",
            "label": "数据类型",
            "options": ["auto", "request", "response"],
            "default": "auto",
            "option_labels": {"auto": "自动探测", "request": "请求体", "response": "响应体"},
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "converted", "type": "object"},
        {"name": "json", "type": "string", "canvas": False},
        {"name": "source", "type": "string", "canvas": False},
        {"name": "target", "type": "string", "canvas": False},
        {"name": "kind", "type": "string", "canvas": False},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    del context
    raw = params.get("payload")
    if isinstance(raw, dict):
        payload = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return _fail(f"JSON 解析失败：{exc}")
    else:
        return _fail("数据为空")
    if not isinstance(payload, dict):
        return _fail("数据必须是 JSON 对象")

    try:
        kind = str(params.get("kind") or "auto").strip().lower()
        if kind not in ("request", "response"):
            kind = core.detect_kind(payload)
        src = core.resolve_source(params.get("source"), payload, request=(kind == "request"))
        tgt = core.resolve_target(params.get("target"), src)
        converted = core.convert(payload, source=src, target=tgt, kind=kind)
    except ValueError as exc:
        return _fail(str(exc))
    except Exception as exc:  # noqa: BLE001 - 积木面向用户，异常一律转 error 字符串
        return _fail(f"转换失败：{exc}")

    return {
        "ok": True,
        "converted": converted,
        "json": json.dumps(converted, ensure_ascii=False),
        "source": src,
        "target": tgt,
        "kind": kind,
        "error": "",
    }


def _fail(err: str) -> dict:
    return {
        "ok": False,
        "converted": None,
        "json": "",
        "source": "",
        "target": "",
        "kind": "",
        "error": err,
    }
