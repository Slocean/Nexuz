"""LLM API 格式互转内核：chat/completions ↔ responses。

被 llm_convert（纯转换积木）与 llm_forward（转发积木的内置转换）共用。
纯函数、不改输入、不发网络；只做结构映射。流式（SSE 分片）不在转换范围。

映射口径（v1）：
- 请求：messages↔input、max_tokens↔max_output_tokens、tools 扁平化、
  tool_choice 结构、response_format↔text.format、instructions↔system 消息；
- 响应：choices[0]↔output、finish_reason↔status/incomplete_details、
  usage 计数词换名；仅映射第一个 choice（responses 无 n>1 等价物）；
- 部件：text↔input_text/output_text、image_url↔input_image；
- 错误体：任何一方的 {"error": ...} 都会包成对方格式的错误结构传递，代理场景
  下调用方必须能看到端点报错；
- reasoning 等无法等价表达的项直接丢弃（responses reasoning 在 chat 侧没有
  载体，chat 推理字段在 responses 侧同理）。
"""

from __future__ import annotations

import json
from typing import Any

CHAT = "chat"
RESPONSES = "responses"
UNKNOWN = "unknown"

# ---------------------------------------------------------------------------
# 格式探测
# ---------------------------------------------------------------------------


def detect_kind(payload: Any) -> str:
    """区分请求（request）与响应（response）。两者字段不相交，可按特征判别。"""
    if isinstance(payload, dict):
        obj = str(payload.get("object") or "")
        if obj == "response" or obj.startswith("chat.completion"):
            return "response"
        if isinstance(payload.get("choices"), list) or isinstance(payload.get("output"), list):
            return "response"
        if isinstance(payload.get("messages"), list) or "input" in payload:
            return "request"
    raise ValueError("无法识别数据类型（请求/响应），请手动指定 kind")


def detect_request_format(payload: Any) -> str:
    if isinstance(payload, dict):
        if isinstance(payload.get("messages"), list):
            return CHAT
        if "input" in payload:
            return RESPONSES
    return UNKNOWN


def detect_response_format(payload: Any) -> str:
    if isinstance(payload, dict):
        obj = str(payload.get("object") or "")
        if obj.startswith("chat.completion") or isinstance(payload.get("choices"), list):
            return CHAT
        if obj == "response" or isinstance(payload.get("output"), list):
            return RESPONSES
    return UNKNOWN


def resolve_source(value: Any, payload: dict, *, request: bool) -> str:
    """source 参数落地：显式指定优先，auto 则探测。"""
    v = str(value or "auto").strip().lower()
    if v in (CHAT, RESPONSES):
        return v
    return detect_request_format(payload) if request else detect_response_format(payload)


def resolve_target(value: Any, source: str) -> str:
    """target 参数落地：auto 表示与源一致（透明转发，不做转换）。"""
    v = str(value or "auto").strip().lower()
    if v in (CHAT, RESPONSES):
        return v
    return source


# ---------------------------------------------------------------------------
# 统一转换入口
# ---------------------------------------------------------------------------

_CONVERTERS: dict[tuple[str, str, str], Any] = {}


def convert(payload: dict, *, source: str, target: str, kind: str) -> dict:
    """按 (source, target, kind) 分发到具体转换函数。返回新对象，不改输入。"""
    if not isinstance(payload, dict):
        raise ValueError("payload 必须是 JSON 对象")
    if kind not in ("request", "response"):
        kind = detect_kind(payload)
    if source == target:
        return dict(payload)
    fn = _CONVERTERS.get((source, target, kind))
    if fn is None:
        raise ValueError(f"不支持的转换路径：{source} → {target}（{kind}）")
    return fn(payload)


def _register(source: str, target: str, kind: str):
    def deco(fn):
        _CONVERTERS[(source, target, kind)] = fn
        return fn

    return deco


def _require_dict(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload 必须是 JSON 对象")
    return payload


def _dump_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _copy_known(src: dict, dst: dict, keys: tuple[str, ...]) -> None:
    for key in keys:
        if src.get(key) is not None:
            dst[key] = src[key]


# ---------------------------------------------------------------------------
# content 部件互转
# ---------------------------------------------------------------------------


def _as_text(content: Any) -> str:
    """从任一侧的 content（字符串 / 部件数组）抽纯文本。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("text") is not None:
                parts.append(str(part["text"]))
        return "".join(parts)
    return str(content)


def _chat_content_to_responses(content: Any, role: str) -> Any:
    """chat content → responses content。assistant 回填需用 output_text 部件。"""
    if isinstance(content, str):
        if role == "assistant":
            return [{"type": "output_text", "text": content, "annotations": []}]
        return content  # user/system 的字符串 content 两侧通用
    if not isinstance(content, list):
        return content
    parts: list[dict] = []
    for part in content:
        if isinstance(part, str):
            ptype = "output_text" if role == "assistant" else "input_text"
            parts.append({"type": ptype, "text": part})
            continue
        if not isinstance(part, dict):
            parts.append(part)
            continue
        ptype = part.get("type")
        if ptype in ("text", "input_text", "output_text"):
            new_type = "output_text" if role == "assistant" else "input_text"
            new = {"type": new_type, "text": part.get("text") or ""}
            if role == "assistant":
                new["annotations"] = part.get("annotations") or []
            parts.append(new)
        elif ptype in ("image_url", "input_image"):
            url = part.get("image_url")
            if isinstance(url, dict):
                url = url.get("url")
            parts.append({"type": "input_image", "image_url": url})
        else:
            parts.append(part)
    return parts


def _responses_content_to_chat(content: Any) -> Any:
    """responses content → chat content。纯文本压回字符串，兼容面最大。"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return content
    parts: list[dict] = []
    for part in content:
        if isinstance(part, str):
            parts.append({"type": "text", "text": part})
            continue
        if not isinstance(part, dict):
            parts.append(part)
            continue
        ptype = part.get("type")
        if ptype in ("text", "input_text", "output_text"):
            parts.append({"type": "text", "text": part.get("text") or ""})
        elif ptype in ("image_url", "input_image"):
            url = part.get("image_url")
            if isinstance(url, dict):
                url = url.get("url")
            parts.append({"type": "image_url", "image_url": {"url": url}})
        else:
            parts.append(part)
    if parts and all(p.get("type") == "text" for p in parts if isinstance(p, dict)):
        return "".join(str(p.get("text") or "") for p in parts if isinstance(p, dict))
    return parts


# ---------------------------------------------------------------------------
# tools / tool_choice / response_format 互转
# ---------------------------------------------------------------------------


def _tool_chat_to_responses(tool: Any) -> Any:
    if not isinstance(tool, dict) or tool.get("type") != "function":
        return tool
    fn = tool.get("function") or {}
    out: dict = {"type": "function"}
    _copy_known(fn, out, ("name", "description", "parameters", "strict"))
    return out


def _tool_responses_to_chat(tool: Any) -> Any:
    if not isinstance(tool, dict) or tool.get("type") != "function":
        return tool
    fn: dict = {}
    _copy_known(tool, fn, ("name", "description", "parameters", "strict"))
    return {"type": "function", "function": fn}


def _tool_choice_chat_to_responses(tc: Any) -> Any:
    if isinstance(tc, dict) and tc.get("type") == "function":
        return {"type": "function", "name": (tc.get("function") or {}).get("name")}
    return tc


def _tool_choice_responses_to_chat(tc: Any) -> Any:
    if isinstance(tc, dict) and tc.get("type") == "function" and "name" in tc:
        return {"type": "function", "function": {"name": tc.get("name")}}
    return tc


def _response_format_chat_to_responses(rf: dict) -> dict | None:
    t = rf.get("type")
    if t == "json_object":
        return {"type": "json_object"}
    if t == "json_schema":
        js = rf.get("json_schema") or {}
        fmt: dict = {"type": "json_schema", "name": js.get("name") or "response", "schema": js.get("schema")}
        if js.get("strict") is not None:
            fmt["strict"] = js["strict"]
        return fmt
    if t == "text":
        return {"type": "text"}
    return None


def _response_format_responses_to_chat(fmt: dict) -> dict | None:
    t = fmt.get("type")
    if t == "json_object":
        return {"type": "json_object"}
    if t == "json_schema":
        js: dict = {"name": fmt.get("name"), "schema": fmt.get("schema")}
        if fmt.get("strict") is not None:
            js["strict"] = fmt["strict"]
        return {"type": "json_schema", "json_schema": js}
    if t == "text":
        return {"type": "text"}
    return None


# ---------------------------------------------------------------------------
# usage 计数换名
# ---------------------------------------------------------------------------


def _usage_chat_to_responses(usage: Any) -> dict | None:
    if not isinstance(usage, dict):
        return None
    out = {
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }
    for src, dst in (("prompt_tokens_details", "input_tokens_details"), ("completion_tokens_details", "output_tokens_details")):
        if usage.get(src) is not None:
            out[dst] = usage[src]
    return out


def _usage_responses_to_chat(usage: Any) -> dict | None:
    if not isinstance(usage, dict):
        return None
    out = {
        "prompt_tokens": usage.get("input_tokens"),
        "completion_tokens": usage.get("output_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }
    for src, dst in (("input_tokens_details", "prompt_tokens_details"), ("output_tokens_details", "completion_tokens_details")):
        if usage.get(src) is not None:
            out[dst] = usage[src]
    return out


# ---------------------------------------------------------------------------
# 请求转换
# ---------------------------------------------------------------------------


@_register(CHAT, RESPONSES, "request")
def chat_to_responses_request(payload: dict) -> dict:
    payload = _require_dict(payload)
    if not isinstance(payload.get("messages"), list):
        raise ValueError("chat 请求缺少 messages 数组")
    input_items: list[dict] = []
    for msg in payload["messages"]:
        if not isinstance(msg, dict):
            raise ValueError("messages项必须是对象")
        role = str(msg.get("role") or "user")
        if role == "tool":
            output = msg.get("content")
            if not isinstance(output, str):
                output = _dump_json(output)
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(msg.get("tool_call_id") or ""),
                    "output": output,
                }
            )
            continue
        content = msg.get("content")
        if content is not None and content != "":
            input_items.append({"role": role, "content": _chat_content_to_responses(content, role)})
        for call in msg.get("tool_calls") or []:
            fn = call.get("function") or {}
            args = fn.get("arguments")
            input_items.append(
                {
                    "type": "function_call",
                    "call_id": call.get("id") or call.get("call_id") or "",
                    "name": fn.get("name"),
                    "arguments": args if isinstance(args, str) else _dump_json(args),
                }
            )
    out: dict = {"input": input_items}
    _copy_known(payload, out, ("model", "temperature", "top_p", "stream", "parallel_tool_calls", "metadata", "user", "store"))
    if payload.get("max_tokens") is not None:
        out["max_output_tokens"] = payload["max_tokens"]
    elif payload.get("max_completion_tokens") is not None:
        out["max_output_tokens"] = payload["max_completion_tokens"]
    tools = payload.get("tools")
    if isinstance(tools, list) and tools:
        out["tools"] = [_tool_chat_to_responses(t) for t in tools]
    if payload.get("tool_choice") is not None:
        out["tool_choice"] = _tool_choice_chat_to_responses(payload["tool_choice"])
    rf = payload.get("response_format")
    if isinstance(rf, dict):
        fmt = _response_format_chat_to_responses(rf)
        if fmt is not None:
            out["text"] = {"format": fmt}
    return out


@_register(RESPONSES, CHAT, "request")
def responses_to_chat_request(payload: dict) -> dict:
    payload = _require_dict(payload)
    if "input" not in payload:
        raise ValueError("responses 请求缺少 input 字段")
    raw_input = payload["input"]
    messages: list[dict] = []
    if isinstance(raw_input, str):
        messages.append({"role": "user", "content": raw_input})
    elif isinstance(raw_input, list):
        pending_calls: list[dict] = []

        def _flush_calls() -> None:
            if pending_calls:
                messages.append({"role": "assistant", "content": None, "tool_calls": list(pending_calls)})
                pending_calls.clear()

        for item in raw_input:
            if isinstance(item, str):
                _flush_calls()
                messages.append({"role": "user", "content": item})
                continue
            if not isinstance(item, dict):
                raise ValueError("input 项必须是对象或字符串")
            itype = item.get("type")
            if itype == "function_call":
                args = item.get("arguments")
                pending_calls.append(
                    {
                        "id": item.get("call_id") or item.get("id") or "",
                        "type": "function",
                        "function": {"name": item.get("name"), "arguments": args if isinstance(args, str) else _dump_json(args)},
                    }
                )
                continue
            if itype == "function_call_output":
                _flush_calls()
                output = item.get("output")
                if not isinstance(output, str):
                    output = _dump_json(output)
                messages.append({"role": "tool", "tool_call_id": str(item.get("call_id") or ""), "content": output})
                continue
            if itype == "reasoning":
                continue  # chat 侧无等价载体
            _flush_calls()
            role = str(item.get("role") or "user")
            messages.append({"role": role, "content": _responses_content_to_chat(item.get("content"))})
        _flush_calls()
    else:
        raise ValueError("input 必须是字符串或数组")
    instructions = payload.get("instructions")
    if instructions:
        messages.insert(0, {"role": "system", "content": str(instructions)})
    out: dict = {"messages": messages}
    _copy_known(payload, out, ("model", "temperature", "top_p", "stream", "parallel_tool_calls", "metadata", "user", "store"))
    if payload.get("max_output_tokens") is not None:
        out["max_tokens"] = payload["max_output_tokens"]
    tools = payload.get("tools")
    if isinstance(tools, list) and tools:
        out["tools"] = [_tool_responses_to_chat(t) for t in tools]
    if payload.get("tool_choice") is not None:
        out["tool_choice"] = _tool_choice_responses_to_chat(payload["tool_choice"])
    text_cfg = payload.get("text")
    if isinstance(text_cfg, dict) and isinstance(text_cfg.get("format"), dict):
        rf = _response_format_responses_to_chat(text_cfg["format"])
        if rf is not None:
            out["response_format"] = rf
    return out


# ---------------------------------------------------------------------------
# 响应转换
# ---------------------------------------------------------------------------


@_register(CHAT, RESPONSES, "response")
def chat_to_responses_response(payload: dict) -> dict:
    payload = _require_dict(payload)
    error = payload.get("error")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        if error is not None:
            return {"object": "response", "status": "failed", "error": error, "output": []}
        raise ValueError("chat 响应缺少 choices 数组")
    choice = choices[0] if isinstance(choices[0], dict) else {}
    msg = choice.get("message") or {}
    output: list[dict] = []
    content = msg.get("content")
    text = _as_text(content)
    if content is not None:
        output.append(
            {
                "type": "message",
                "id": "msg_conv_0",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        )
    for i, call in enumerate(msg.get("tool_calls") or []):
        fn = call.get("function") or {}
        args = fn.get("arguments")
        output.append(
            {
                "type": "function_call",
                "id": f"fc_conv_{i}",
                "call_id": call.get("id") or "",
                "name": fn.get("name"),
                "arguments": args if isinstance(args, str) else _dump_json(args),
            }
        )
    resp: dict = {
        "id": payload.get("id") or "resp_conv",
        "object": "response",
        "created_at": payload.get("created"),
        "model": payload.get("model"),
        "output": output,
        "output_text": text,
        "status": "completed",
    }
    usage = _usage_chat_to_responses(payload.get("usage"))
    if usage is not None:
        resp["usage"] = usage
    if choice.get("finish_reason") == "length":
        resp["status"] = "incomplete"
        resp["incomplete_details"] = {"reason": "max_output_tokens"}
    if error is not None:
        resp["error"] = error
        resp["status"] = "failed"
    return resp


@_register(RESPONSES, CHAT, "response")
def responses_to_chat_response(payload: dict) -> dict:
    payload = _require_dict(payload)
    error = payload.get("error")
    output = payload.get("output")
    if not isinstance(output, list):
        if error is not None:
            return {"object": "chat.completion", "error": error, "choices": []}
        raise ValueError("responses 响应缺少 output 数组")
    text_parts: list[str] = []
    refusal = ""
    tool_calls: list[dict] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        itype = item.get("type") or ("message" if item.get("role") else "")
        if itype == "message":
            for part in item.get("content") or []:
                if isinstance(part, str):
                    text_parts.append(part)
                elif isinstance(part, dict):
                    if part.get("type") in ("output_text", "text", "input_text"):
                        text_parts.append(str(part.get("text") or ""))
                    elif part.get("type") == "refusal":
                        refusal = str(part.get("refusal") or "")
        elif itype == "function_call":
            args = item.get("arguments")
            tool_calls.append(
                {
                    "id": item.get("call_id") or item.get("id") or "",
                    "type": "function",
                    "function": {"name": item.get("name"), "arguments": args if isinstance(args, str) else _dump_json(args)},
                }
            )
    text = "".join(text_parts)
    if tool_calls:
        finish = "tool_calls"
    elif payload.get("status") == "incomplete":
        finish = "length"
    else:
        finish = "stop"
    message: dict = {"role": "assistant", "content": text if text else None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    if refusal:
        message["refusal"] = refusal
    resp: dict = {
        "id": payload.get("id") or "chatcmpl_conv",
        "object": "chat.completion",
        "created": payload.get("created_at"),
        "model": payload.get("model"),
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
    }
    usage = _usage_responses_to_chat(payload.get("usage"))
    if usage is not None:
        resp["usage"] = usage
    if error is not None:
        resp["error"] = error
    return resp


# ---------------------------------------------------------------------------
# 响应文本抽取（转发积木的 text 输出）
# ---------------------------------------------------------------------------


def extract_response_text(payload: Any) -> str:
    """尽力从 chat 或 responses 响应里抽助手文本，抽不到返回空串。"""
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return _as_text((choices[0].get("message") or {}).get("content"))
    output = payload.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if isinstance(item, dict) and (item.get("type") == "message" or (not item.get("type") and item.get("role"))):
                parts.append(_as_text(item.get("content")))
        return "".join(parts)
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    return ""
