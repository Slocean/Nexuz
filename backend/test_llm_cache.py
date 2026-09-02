"""llm_cache：键稳定性、KV 往返、TTL 与 guarded_structured_invoke 命中。"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from backend.core.ai import llm_cache


class _Probe(BaseModel):
    ok: bool
    tag: str = ""


class _Msg:
    """LangChain Message 形状（type/content）。"""

    def __init__(self, type_: str, content: str):
        self.type = type_
        self.content = content


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    cache_root = tmp_path / "ai"

    def _ai_dir(*, create: bool = False):
        if create:
            cache_root.mkdir(parents=True, exist_ok=True)
        return cache_root

    monkeypatch.setattr("backend.paths.ai_dir", _ai_dir)
    monkeypatch.setattr("backend.paths.config_path", lambda: tmp_path / "config.json")
    monkeypatch.delenv("NEXUZ_AI_LLM_CACHE_TTL_HOURS", raising=False)
    llm_cache.close_cache()
    yield tmp_path
    llm_cache.close_cache()


def test_make_key_stable_and_sensitive(isolated_cache):
    msgs = [("system", "SYS"), ("user", "hello")]
    k1 = llm_cache.make_key(purpose="understand", model="m1", messages=msgs)
    k2 = llm_cache.make_key(purpose="understand", model="m1", messages=msgs)
    assert k1 == k2
    assert llm_cache.make_key(purpose="plan_ir", model="m1", messages=msgs) != k1
    assert llm_cache.make_key(purpose="understand", model="m2", messages=msgs) != k1
    assert llm_cache.make_key(
        purpose="understand", model="m1", messages=[("system", "SYS"), ("user", "world")]
    ) != k1


def test_message_forms_normalize(isolated_cache):
    tuple_msgs = [("system", "S"), ("user", "U")]
    dict_msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    obj_msgs = [_Msg("system", "S"), _Msg("user", "U")]
    base = llm_cache.make_key(purpose="p", model="m", messages=tuple_msgs)
    assert llm_cache.make_key(purpose="p", model="m", messages=dict_msgs) == base
    assert llm_cache.make_key(purpose="p", model="m", messages=obj_msgs) == base


def test_multimodal_image_hashed_stable(isolated_cache):
    data_url = "data:image/png;base64,AAAA" * 500
    m1 = [{"role": "user", "content": [{"type": "text", "text": "x"}, {"type": "image_url", "image_url": {"url": data_url}}]}]
    m2 = [{"role": "user", "content": [{"type": "text", "text": "x"}, {"type": "image_url", "image_url": {"url": data_url}}]}]
    m3 = [{"role": "user", "content": [{"type": "text", "text": "x"}]}]
    assert llm_cache.make_key(purpose="v", model="m", messages=m1) == llm_cache.make_key(
        purpose="v", model="m", messages=m2
    )
    assert llm_cache.make_key(purpose="v", model="m", messages=m1) != llm_cache.make_key(
        purpose="v", model="m", messages=m3
    )


def test_kv_roundtrip_and_ttl(isolated_cache, monkeypatch):
    llm_cache.put_json("k1", {"a": 1})
    assert llm_cache.get_json("k1") == {"a": 1}
    llm_cache.put_blob("b1", b"\x89PNG")
    assert llm_cache.get_blob("b1") == b"\x89PNG"

    monkeypatch.setenv("NEXUZ_AI_LLM_CACHE_TTL_HOURS", "0")
    assert llm_cache.get_json("k1") is None
    assert llm_cache.get_blob("b1") is None


def test_enabled_flag(isolated_cache):
    from backend.core.ai.types import AiConfig

    assert llm_cache.enabled(AiConfig()) is True
    assert llm_cache.enabled(AiConfig(llm_cache_enabled=False)) is False


def test_structured_roundtrip(isolated_cache):
    key = llm_cache.make_key(purpose="understand", model="m", messages=[("user", "u")])
    assert llm_cache.load_structured(key, _Probe) is None
    llm_cache.store_structured(key, _Probe(ok=True, tag="t"))
    hit = llm_cache.load_structured(key, _Probe)
    assert isinstance(hit, _Probe)
    assert hit.ok and hit.tag == "t"
    # schema 漂移 → 视为未命中
    class _Other(BaseModel):
        need: str

    assert llm_cache.load_structured(key, _Other) is None


def test_guarded_structured_invoke_cache_hit(isolated_cache):
    from backend.core.ai.token_scheduler.generate import guarded_structured_invoke

    calls = {"n": 0}

    class _Bound:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, messages, config=None):
            calls["n"] += 1
            return self.schema(ok=True, tag="gen")

    class _LLM:
        def with_structured_output(self, schema, method=None):
            return _Bound(schema)

    msgs = [_Msg("system", "SYS"), _Msg("user", "hi")]
    r1 = guarded_structured_invoke(
        None,
        "understand",
        _Probe,
        msgs,
        temperature=0.1,
        create_model=lambda *a, **k: _LLM(),
    )
    assert calls["n"] == 1
    r2 = guarded_structured_invoke(
        None,
        "understand",
        _Probe,
        msgs,
        temperature=0.1,
        create_model=lambda *a, **k: _LLM(),
    )
    assert calls["n"] == 1  # 第二次命中缓存，未再触达模型
    assert r2 == r1

    # 不同输入 → miss
    guarded_structured_invoke(
        None,
        "understand",
        _Probe,
        [_Msg("system", "SYS"), _Msg("user", "different")],
        temperature=0.1,
        create_model=lambda *a, **k: _LLM(),
    )
    assert calls["n"] == 2


def test_guarded_structured_invoke_cache_disabled(isolated_cache, monkeypatch):
    from backend.core.ai.types import AiConfig
    from backend.core.ai.token_scheduler.generate import guarded_structured_invoke

    calls = {"n": 0}

    class _Bound:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, messages, config=None):
            calls["n"] += 1
            return self.schema(ok=True)

    class _LLM:
        def with_structured_output(self, schema, method=None):
            return _Bound(schema)

    cfg = AiConfig(llm_cache_enabled=False)
    msgs = [_Msg("user", "hi")]
    guarded_structured_invoke(
        cfg, "understand", _Probe, msgs, temperature=0.1,
        create_model=lambda *a, **k: _LLM(),
    )
    guarded_structured_invoke(
        cfg, "understand", _Probe, msgs, temperature=0.1,
        create_model=lambda *a, **k: _LLM(),
    )
    assert calls["n"] == 2


def test_hit_rate_metrics(isolated_cache, monkeypatch):
    llm_cache.put_json("k1", {"a": 1})
    assert llm_cache.get_json("k1") == {"a": 1}  # hit
    assert llm_cache.get_json("nope") is None  # miss
    monkeypatch.setenv("NEXUZ_AI_LLM_CACHE_TTL_HOURS", "0")
    assert llm_cache.get_json("k1") is None  # miss_expired

    stats = llm_cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 2
    assert stats["miss_expired"] == 1
    assert stats["hit_rate"] == round(1 / 3, 4)

    # 手动清空 → 指标一并归零
    assert llm_cache.clear() == 1
    stats = llm_cache.stats()
    assert stats["hits"] == 0 and stats["hit_rate"] is None
