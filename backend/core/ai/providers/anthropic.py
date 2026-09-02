"""Anthropic Messages API 原生适配器（legacy client 路径）。

实现 Anthropic /v1/messages 协议（非 OpenAI 兼容伪装）：
- system 消息从 messages 提取到顶层 system 参数；
- OpenAI tool_calls / role=tool 消息 ↔ Anthropic tool_use / tool_result 块互转；
- max_tokens 为必填，默认 4096；
- usage 透传（input_tokens/output_tokens）。

生产编排仍走 LangChain ChatOpenAI（OpenAI 兼容网关）；本客户端服务于
provider=anthropic 的 legacy 直连场景与单测。
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin

import httpx

from backend.core.ai.model_capabilities import fixed_temperature
from backend.core.ai.types import LlmError, LlmTurn

_ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MAX_TOKENS = 4096


def _messages_url(base_url: str) -> str:
    base = (base_url or "https://api.anthropic.com").strip().rstrip("/")
    if base.endswith("/messages"):
        return base
    # 允许用户填到 /v1 或只填域名
    if base.endswith("/v1"):
        return f"{base}/messages"
    return urljoin(base + "/", "v1/messages")


def _to_anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """OpenAI 风格消息 → (system, [{role, content}])。

    支持：system 提取；assistant 的 tool_calls → tool_use 块；role=tool →
    tool_result 块（Anthropic 要求 tool_result 放在 user 消息内）。
    """
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []

    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "")
        content = msg.get("content")
        if role == "system":
            if isinstance(content, list):
                content = "".join(str(p) for p in content)
            if str(content or "").strip():
                system_parts.append(str(content))
            continue

        if role == "tool":
            # Anthropic 协议：tool_result 必须放在紧跟 assistant(tool_use) 的
            # user 消息内，不能混入 assistant 自身的 content
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": str(msg.get("tool_call_id") or ""),
                            "content": "" if content is None else str(content),
                        }
                    ],
                }
            )
            continue

        blocks: list[dict[str, Any]] = []
        text = "" if content is None else str(content)
        if text:
            blocks.append({"type": "text", "text": text})
        for call in msg.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            fn = call.get("function") if isinstance(call.get("function"), dict) else {}
            raw_args = fn.get("arguments")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
            except Exception:
                args = {}
            blocks.append(
                {"type": "tool_use", "id": str(call.get("id") or ""), "name": str(fn.get("name") or ""), "input": args}
            )
        if not blocks:
            continue
        if len(blocks) == 1 and blocks[0]["type"] == "text":
            out.append({"role": "user" if role == "user" else "assistant", "content": blocks[0]["text"]})
        else:
            out.append({"role": "user" if role == "user" else "assistant", "content": blocks})
    return "\n\n".join(system_parts), out


def _to_openai_tool_calls(content_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for block in content_blocks or []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        calls.append(
            {
                "id": str(block.get("id") or ""),
                "type": "function",
                "function": {
                    "name": str(block.get("name") or ""),
                    "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                },
            }
        )
    return calls


class AnthropicClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.7,
        timeout_s: float = 120.0,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        http_client: httpx.Client | None = None,
    ):
        self.base_url = base_url
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip() or "claude-sonnet-4-5"
        self.temperature = min(1.0, max(0.0, float(temperature)))
        self.timeout_s = float(timeout_s)
        self.max_tokens = int(max_tokens)
        self._client = http_client
        self._owns_client = http_client is None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout_s)
        return self._client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        model: str | None = None,
        temperature: float | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LlmTurn:
        if not self.api_key:
            raise LlmError("未配置 API Key（Anthropic 需要 sk-ant-... 密钥）")

        use_model = (model or self.model).strip() or self.model
        use_temp = self.temperature if temperature is None else min(1.0, max(0.0, float(temperature)))
        fixed = fixed_temperature(use_model)
        if fixed is not None:
            use_temp = min(1.0, fixed)

        system, convo = _to_anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": use_model,
            "max_tokens": self.max_tokens,
            "temperature": use_temp,
            "messages": convo,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": str(t.get("function", {}).get("name") or t.get("name") or ""),
                    "description": str(
                        t.get("function", {}).get("description") or t.get("description") or ""
                    ),
                    "input_schema": t.get("function", {}).get(
                        "parameters", {"type": "object", "properties": {}}
                    ),
                }
                for t in tools
                if isinstance(t, dict)
            ]
        if tool_choice == "required":
            payload["tool_choice"] = {"type": "any"}
        elif isinstance(tool_choice, dict) and tool_choice.get("function", {}).get("name"):
            payload["tool_choice"] = {"type": "tool", "name": tool_choice["function"]["name"]}

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
        }

        try:
            resp = self._get_client().post(_messages_url(self.base_url), json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LlmError(f"请求超时（{self.timeout_s:.0f}s）") from exc
        except httpx.HTTPError as exc:
            raise LlmError(f"网络错误: {exc}") from exc

        if resp.status_code >= 400:
            raise LlmError(f"HTTP {resp.status_code}: {(resp.text or '')[:300]}")
        try:
            data = resp.json()
        except Exception as exc:
            raise LlmError("响应不是 JSON") from exc

        blocks = data.get("content") if isinstance(data.get("content"), list) else []
        text = "".join(
            str(b.get("text") or "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"
        )
        usage_raw = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return LlmTurn(
            content=text,
            tool_calls=_to_openai_tool_calls(blocks),
            usage={
                "input_tokens": usage_raw.get("input_tokens"),
                "output_tokens": usage_raw.get("output_tokens"),
            }
            if usage_raw
            else None,
            raw=data,
        )
