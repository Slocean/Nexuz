"""OpenAI-compatible Chat Completions client (covers most vendors via base_url)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin

import httpx

from backend.core.ai.types import LlmError, LlmTurn

# Models that reject non-default temperature (must be 1 or omitted).
_FIXED_TEMP_1_MARKERS = (
    "o1",
    "o3",
    "o4",
    "gpt-5",
    "reasoner",
    "deepseek-r1",
    "kimi",
    "k2.5",
    "k2-",
)


def _normalize_base_url(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise LlmError("未配置 Base URL")
    return url + "/"


def _chat_url(base_url: str) -> str:
    base = _normalize_base_url(base_url)
    # Avoid double /v1/v1 if user already included path
    if base.rstrip("/").endswith("/chat/completions"):
        return base.rstrip("/")
    return urljoin(base, "chat/completions")


def _model_requires_temperature_one(model: str) -> bool:
    name = (model or "").strip().lower()
    if not name:
        return False
    return any(m in name for m in _FIXED_TEMP_1_MARKERS)


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pass through OpenAI message shapes, including tool / tool_calls."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        entry: dict[str, Any] = {"role": role}
        if "content" in m:
            entry["content"] = m.get("content")
        if role == "assistant" and m.get("tool_calls"):
            entry["tool_calls"] = m["tool_calls"]
            if entry.get("content") is None:
                entry["content"] = None
        if role == "tool":
            if m.get("tool_call_id"):
                entry["tool_call_id"] = str(m["tool_call_id"])
            if m.get("name"):
                entry["name"] = str(m["name"])
            if "content" not in entry:
                entry["content"] = ""
        out.append(entry)
    return out


class OpenAiCompatClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.7,
        timeout_s: float = 120.0,
        http_client: httpx.Client | None = None,
    ):
        self.base_url = base_url
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip() or "gpt-4o-mini"
        self.temperature = float(temperature)
        self.timeout_s = float(timeout_s)
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
        if not self.api_key and "127.0.0.1" not in (self.base_url or "") and "localhost" not in (
            self.base_url or ""
        ):
            # Ollama often needs no key; other vendors need one.
            pass
        if not self.api_key and not any(
            h in (self.base_url or "").lower() for h in ("127.0.0.1", "localhost", "0.0.0.0")
        ):
            raise LlmError("未配置 API Key，请先在设置中填写")

        use_model = (model or self.model).strip() or self.model
        use_temp = self.temperature if temperature is None else float(temperature)
        if _model_requires_temperature_one(use_model):
            use_temp = 1.0

        payload: dict[str, Any] = {
            "model": use_model,
            "messages": _normalize_messages(messages),
            "temperature": use_temp,
        }
        if tools:
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
            else:
                payload["tool_choice"] = "auto"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
        }
        if not self.api_key:
            headers.pop("Authorization", None)

        url = _chat_url(self.base_url)
        try:
            resp = self._get_client().post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LlmError(f"请求超时（{self.timeout_s:.0f}s）") from exc
        except httpx.HTTPError as exc:
            raise LlmError(f"网络错误: {exc}") from exc

        # Some gateways reject non-1 temperature only at runtime — one retry.
        if (
            resp.status_code == 400
            and "temperature" in (resp.text or "").lower()
            and float(use_temp) != 1.0
        ):
            payload = {**payload, "temperature": 1.0}
            try:
                resp = self._get_client().post(url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                raise LlmError(f"请求超时（{self.timeout_s:.0f}s）") from exc
            except httpx.HTTPError as exc:
                raise LlmError(f"网络错误: {exc}") from exc

        if resp.status_code >= 400:
            detail = _extract_error_detail(resp)
            raise LlmError(
                f"LLM 请求失败 ({resp.status_code}): {detail}",
                status_code=resp.status_code,
            )

        try:
            data = resp.json()
        except Exception as exc:
            raise LlmError("响应不是合法 JSON") from exc

        content, tool_calls, reasoning = _extract_message(data)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
        return LlmTurn(
            content=content,
            tool_calls=tool_calls,
            reasoning=reasoning,
            usage=usage,
            raw=data,
        )

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        model: str | None = None,
        temperature: float | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_delta: Any = None,
    ) -> LlmTurn:
        """Stream chat completions; call on_delta({"type","text"}) for text/reasoning chunks."""
        if not self.api_key and not any(
            h in (self.base_url or "").lower() for h in ("127.0.0.1", "localhost", "0.0.0.0")
        ):
            raise LlmError("未配置 API Key，请先在设置中填写")

        use_model = (model or self.model).strip() or self.model
        use_temp = self.temperature if temperature is None else float(temperature)
        if _model_requires_temperature_one(use_model):
            use_temp = 1.0

        payload: dict[str, Any] = {
            "model": use_model,
            "messages": _normalize_messages(messages),
            "temperature": use_temp,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice if tool_choice is not None else "auto"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
            "Accept": "text/event-stream",
        }
        if not self.api_key:
            headers.pop("Authorization", None)

        url = _chat_url(self.base_url)

        try:
            return self._consume_chat_stream(url, payload, headers, on_delta=on_delta)
        except LlmError as exc:
            # Same runtime retry as non-stream chat for gateways that only accept temp=1.
            if (
                exc.status_code == 400
                and "temperature" in (exc.message or "").lower()
                and float(payload.get("temperature") or 0) != 1.0
            ):
                payload = {**payload, "temperature": 1.0}
                return self._consume_chat_stream(url, payload, headers, on_delta=on_delta)
            raise

    def _consume_chat_stream(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        *,
        on_delta: Any = None,
    ) -> LlmTurn:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_acc: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] | None = None

        try:
            with self._get_client().stream(
                "POST", url, json=payload, headers=headers, timeout=self.timeout_s
            ) as resp:
                if resp.status_code >= 400:
                    body = resp.read()
                    try:
                        detail = json.loads(body.decode("utf-8", errors="replace"))
                        err = detail.get("error") if isinstance(detail, dict) else None
                        msg = (
                            err.get("message")
                            if isinstance(err, dict)
                            else (
                                err
                                if isinstance(err, str)
                                else body.decode("utf-8", errors="replace")[:300]
                            )
                        )
                    except Exception:
                        msg = body.decode("utf-8", errors="replace")[:300]
                    raise LlmError(
                        f"LLM 请求失败 ({resp.status_code}): {msg}",
                        status_code=resp.status_code,
                    )

                for line in resp.iter_lines():
                    if not line:
                        continue
                    if isinstance(line, bytes):
                        line = line.decode("utf-8", errors="replace")
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(chunk.get("usage"), dict):
                        usage = chunk["usage"]
                    choices = chunk.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice = choices[0] if isinstance(choices[0], dict) else {}
                    delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
                    piece = delta.get("content")
                    if isinstance(piece, str) and piece:
                        content_parts.append(piece)
                        if callable(on_delta):
                            on_delta({"type": "delta", "text": piece})
                    for key in ("reasoning_content", "reasoning"):
                        rpiece = delta.get(key)
                        if isinstance(rpiece, str) and rpiece:
                            reasoning_parts.append(rpiece)
                            if callable(on_delta):
                                on_delta({"type": "reasoning", "text": rpiece})
                            break
                    raw_tcs = delta.get("tool_calls")
                    if isinstance(raw_tcs, list):
                        for tc in raw_tcs:
                            if not isinstance(tc, dict):
                                continue
                            idx = int(tc.get("index") or 0)
                            slot = tool_acc.setdefault(
                                idx,
                                {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                },
                            )
                            if tc.get("id"):
                                slot["id"] = str(tc["id"])
                            if tc.get("type"):
                                slot["type"] = str(tc["type"])
                            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                            if fn.get("name"):
                                slot["function"]["name"] = str(fn["name"])
                            if fn.get("arguments"):
                                slot["function"]["arguments"] = (
                                    str(slot["function"].get("arguments") or "")
                                    + str(fn["arguments"])
                                )
        except LlmError:
            raise
        except httpx.TimeoutException as exc:
            raise LlmError(f"请求超时（{self.timeout_s:.0f}s）") from exc
        except httpx.HTTPError as exc:
            raise LlmError(f"网络错误: {exc}") from exc

        tool_calls = [
            _normalize_tool_call(tool_acc[i]) for i in sorted(tool_acc.keys())
        ]
        tool_calls = [c for c in tool_calls if c.get("id") or c.get("name")]
        return LlmTurn(
            content="".join(content_parts),
            tool_calls=tool_calls,
            reasoning="".join(reasoning_parts),
            usage=usage,
            raw=None,
        )


def _extract_error_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"])
            if isinstance(err, str):
                return err
            if data.get("message"):
                return str(data["message"])
    except Exception:
        pass
    text = (resp.text or "").strip()
    return text[:300] if text else resp.reason_phrase or "unknown error"


def _extract_reasoning(message: dict[str, Any], first: dict[str, Any]) -> str:
    """Pull reasoning / thinking fields from OpenAI-compat vendors."""
    for key in ("reasoning_content", "reasoning", "thinking"):
        val = message.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # Some gateways put it on the choice
    for key in ("reasoning_content", "reasoning"):
        val = first.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _extract_message(data: dict[str, Any]) -> tuple[str, list[dict[str, Any]], str]:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LlmError("响应缺少 choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise LlmError("响应 choices 格式无效")
    message = first.get("message")
    content = ""
    tool_calls: list[dict[str, Any]] = []
    reasoning = ""
    if isinstance(message, dict):
        raw_content = message.get("content")
        if raw_content is not None:
            content = str(raw_content)
        reasoning = _extract_reasoning(message, first)
        raw_calls = message.get("tool_calls")
        if isinstance(raw_calls, list):
            tool_calls = [_normalize_tool_call(c) for c in raw_calls if isinstance(c, dict)]
            tool_calls = [c for c in tool_calls if c.get("id") and c.get("name")]
        return content, tool_calls, reasoning
    if first.get("text") is not None:
        return str(first["text"]), [], ""
    raise LlmError("响应缺少 assistant content")


def _normalize_tool_call(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize to {id, name, arguments(dict)}."""
    call_id = str(raw.get("id") or "")
    fn = raw.get("function") if isinstance(raw.get("function"), dict) else {}
    name = str(fn.get("name") or raw.get("name") or "")
    arguments: Any = fn.get("arguments") if "arguments" in fn else raw.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            arguments = {"_raw": arguments}
    if not isinstance(arguments, dict):
        arguments = {}
    return {
        "id": call_id,
        "type": str(raw.get("type") or "function"),
        "name": name,
        "arguments": arguments,
        "raw": raw,
    }
