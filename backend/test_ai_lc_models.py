"""Tests for LangChain ChatOpenAI factory."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.ai.lc.models import _normalize_base_url, create_chat_model
from backend.core.ai.types import AiConfig


def test_normalize_base_url_strips_completions():
    assert (
        _normalize_base_url("https://api.openai.com/v1/chat/completions")
        == "https://api.openai.com/v1"
    )
    assert _normalize_base_url("https://api.deepseek.com/v1/") == "https://api.deepseek.com/v1"


def test_create_chat_model_from_config():
    cfg = AiConfig(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o-mini",
        temperature=0.2,
    )
    llm = create_chat_model(cfg, streaming=False, temperature=0.2)
    assert llm.model_name == "gpt-4o-mini" or getattr(llm, "model", None) == "gpt-4o-mini"


def test_list_remote_models_parses_openai_shape(monkeypatch):
    from backend.core.ai.lc import models as m

    class FakeResp:
        status_code = 200

        def json(self):
            return {
                "data": [
                    {"id": "qwen2.5-7b-instruct", "owned_by": "local"},
                    {"id": "llama-3.2-3b", "owned_by": "local"},
                ]
            }

        text = ""

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            assert url.rstrip("/").endswith("/models")
            return FakeResp()

    monkeypatch.setattr(m.httpx, "Client", FakeClient)
    out = m.list_remote_models(base_url="http://127.0.0.1:1234/v1", api_key="")
    assert out["ok"] is True
    ids = [x["id"] for x in out["models"]]
    assert "llama-3.2-3b" in ids
    assert "qwen2.5-7b-instruct" in ids
