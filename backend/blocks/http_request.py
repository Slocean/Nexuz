from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

SCHEMA = {
    "type": "http_request",
    "label": "HTTP 请求",
    "category": "系统类",
    "inputs": [
        {
            "name": "method",
            "type": "select",
            "label": "方法",
            "options": ["GET", "POST", "PUT", "PATCH", "DELETE"],
            "default": "GET",
        },
        {
            "name": "url",
            "type": "string",
            "label": "URL",
            "default": "",
            "placeholder": "https://example.com/api",
            "ui": "textarea",
            "bindable": True,
        },
        {
            "name": "headers",
            "type": "keymap",
            "label": "请求头",
            "default": {},
            "ui": "input_map",
        },
        {
            "name": "body",
            "type": "string",
            "label": "请求体",
            "default": "",
            "ui": "textarea",
            "bindable": True,
            "show_when": {"method": ["POST", "PUT", "PATCH"]},
        },
        {
            "name": "timeout_sec",
            "type": "number",
            "label": "超时秒数",
            "default": 30,
        },
        {
            "name": "encoding",
            "type": "string",
            "label": "响应编码",
            "default": "utf-8",
            "placeholder": "utf-8（空则自动猜测）",
            "bindable": True,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "status", "type": "number"},
        {"name": "body", "type": "string"},
        {"name": "error", "type": "string"},
        {"name": "headers", "type": "object", "canvas": False},
    ],
}


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


def handler(params, context, **kwargs):
    method = str(params.get("method") or "GET").strip().upper() or "GET"
    # textarea may wrap long URLs with newlines — strip all whitespace runs
    url = "".join(str(params.get("url") or "").split())
    if not url:
        return {"ok": False, "status": 0, "body": "", "error": "URL 不能为空", "headers": {}}

    headers = _normalize_headers(params.get("headers"))
    body_raw = params.get("body")
    data = None
    if method in ("POST", "PUT", "PATCH", "DELETE") and body_raw not in (None, ""):
        if isinstance(body_raw, (dict, list)):
            payload = json.dumps(body_raw, ensure_ascii=False).encode("utf-8")
            headers.setdefault("Content-Type", "application/json; charset=utf-8")
        else:
            payload = str(body_raw).encode("utf-8")
        data = payload

    try:
        timeout = float(params.get("timeout_sec") if params.get("timeout_sec") not in (None, "") else 30)
    except (TypeError, ValueError):
        timeout = 30.0
    timeout = max(1.0, min(300.0, timeout))

    encoding = str(params.get("encoding") or "").strip()

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", None) or resp.getcode() or 0)
            raw = resp.read()
            resp_headers = {k: v for k, v in resp.headers.items()}
            if encoding:
                try:
                    body = raw.decode(encoding)
                except Exception:
                    body = raw.decode("utf-8", errors="replace")
            else:
                charset = resp.headers.get_content_charset() or "utf-8"
                try:
                    body = raw.decode(charset)
                except Exception:
                    body = raw.decode("utf-8", errors="replace")
            ok = 200 <= status < 300
            return {
                "ok": ok,
                "status": status,
                "body": body,
                "error": "" if ok else f"HTTP {status}",
                "headers": resp_headers,
            }
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read() or b""
        except Exception:
            raw = b""
        if encoding:
            try:
                body = raw.decode(encoding)
            except Exception:
                body = raw.decode("utf-8", errors="replace")
        else:
            body = raw.decode("utf-8", errors="replace")
        status = int(exc.code or 0)
        return {
            "ok": False,
            "status": status,
            "body": body,
            "error": f"HTTP {status}: {exc.reason}",
            "headers": dict(exc.headers.items()) if exc.headers else {},
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": 0,
            "body": "",
            "error": str(exc),
            "headers": {},
        }
