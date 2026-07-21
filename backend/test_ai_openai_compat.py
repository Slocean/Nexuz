"""Tests for OpenAI-compatible LLM client (mocked httpx)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.ai.providers.openai_compat import OpenAiCompatClient, _chat_url
from backend.core.ai.types import LlmError


def test_chat_url_join():
    assert _chat_url("https://api.openai.com/v1").endswith("/chat/completions")
    assert _chat_url("https://api.deepseek.com/v1/").endswith("/chat/completions")


def test_chat_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "hello world"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
    }
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp

    client = OpenAiCompatClient(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o-mini",
        http_client=mock_client,
    )
    turn = client.chat([{"role": "user", "content": "hi"}])
    assert turn.content == "hello world"
    assert turn.usage["completion_tokens"] == 2
    args, kwargs = mock_client.post.call_args
    assert args[0].endswith("/chat/completions")
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
    body = kwargs["json"]
    assert body["model"] == "gpt-4o-mini"
    assert body["messages"][0]["content"] == "hi"


def test_chat_missing_key_remote():
    client = OpenAiCompatClient(
        base_url="https://api.openai.com/v1",
        api_key="",
        model="gpt-4o-mini",
        http_client=MagicMock(),
    )
    try:
        client.chat([{"role": "user", "content": "hi"}])
        assert False, "expected LlmError"
    except LlmError as exc:
        assert "API Key" in exc.message


def test_chat_http_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.reason_phrase = "Unauthorized"
    mock_resp.text = ""
    mock_resp.json.return_value = {"error": {"message": "Invalid API key"}}
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp

    client = OpenAiCompatClient(
        base_url="https://api.openai.com/v1",
        api_key="bad",
        model="m",
        http_client=mock_client,
    )
    try:
        client.chat([{"role": "user", "content": "hi"}])
        assert False, "expected LlmError"
    except LlmError as exc:
        assert "401" in exc.message
        assert "Invalid API key" in exc.message


def test_chat_allows_local_without_key():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "ok"}}],
    }
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp

    client = OpenAiCompatClient(
        base_url="http://127.0.0.1:11434/v1",
        api_key="",
        model="llama3.2",
        http_client=mock_client,
    )
    turn = client.chat([{"role": "user", "content": "ping"}])
    assert turn.content == "ok"
    headers = mock_client.post.call_args.kwargs["headers"]
    assert "Authorization" not in headers


def test_chat_retries_fixed_temperature():
    bad = MagicMock()
    bad.status_code = 400
    bad.text = "invalid temperature: only 1 is allowed for this model"
    bad.reason_phrase = "Bad Request"
    bad.json.return_value = {"error": {"message": "invalid temperature: only 1 is allowed for this model"}}

    good = MagicMock()
    good.status_code = 200
    good.json.return_value = {"choices": [{"message": {"content": "ok"}}]}

    mock_client = MagicMock()
    mock_client.post.side_effect = [bad, good]

    client = OpenAiCompatClient(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="custom-model",
        temperature=0.7,
        http_client=mock_client,
    )
    turn = client.chat([{"role": "user", "content": "hi"}])
    assert turn.content == "ok"
    assert mock_client.post.call_count == 2
    assert mock_client.post.call_args_list[1].kwargs["json"]["temperature"] == 1.0


def test_chat_forces_temp_one_for_reasoner_models():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp

    client = OpenAiCompatClient(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-5-mini",
        temperature=0.7,
        http_client=mock_client,
    )
    client.chat([{"role": "user", "content": "hi"}])
    assert mock_client.post.call_args.kwargs["json"]["temperature"] == 1.0


def test_config_mask_and_roundtrip(tmp_path: Path, monkeypatch):
    from backend.core.ai import config as ai_config

    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(ai_config, "load_app_config", lambda: json.loads(cfg_file.read_text(encoding="utf-8") or "{}"))

    def _save(cfg):
        cfg_file.write_text(json.dumps(cfg), encoding="utf-8")

    monkeypatch.setattr(ai_config, "save_app_config", _save)

    saved = ai_config.set_ai_config(
        {
            "enabled": True,
            "preset": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-secret-1234",
            "model": "deepseek-chat",
        }
    )
    assert saved.api_key == "sk-secret-1234"
    pub = ai_config.public_ai_config(saved)
    assert pub["has_api_key"] is True
    assert "api_key" not in pub
    assert pub["api_key_masked"].endswith("1234")
    assert "*" in pub["api_key_masked"]

    # empty key keeps existing
    saved2 = ai_config.set_ai_config({"model": "deepseek-chat", "api_key": ""})
    assert saved2.api_key == "sk-secret-1234"
