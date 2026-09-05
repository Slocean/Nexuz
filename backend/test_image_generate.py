"""image_generate 节点：请求体构造、URL 拼接、响应解析与存盘。"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from backend.blocks import image_generate
from backend.blocks.image_generate import (
    _build_edit_form,
    _images_edit_url,
    handler,
    _build_body,
    _images_url,
    _resolve_output_target,
)


@pytest.fixture
def image_env(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.paths.config_path", lambda: tmp_path / "config.json"
    )
    for name in ("NEXUZ_AI_IMAGE_BASE_URL", "NEXUZ_AI_IMAGE_API_KEY", "NEXUZ_AI_IMAGE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    # 本文件验证 HTTP 行为（含厂商报错透传），禁用结果缓存避免用例间污染。
    monkeypatch.setenv("NEXUZ_AI_LLM_CACHE", "0")
    from backend.core.ai.config import set_ai_config

    set_ai_config(
        {
            "preset": "custom",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-chat",
            "model": "gpt-4o-mini",
            "image_model": "dall-e-3",
        }
    )
    return tmp_path


def test_images_url_variants():
    assert _images_url("https://api.openai.com/v1") == "https://api.openai.com/v1/images/generations"
    assert (
        _images_url("https://open.bigmodel.cn/api/paas/v4/")
        == "https://open.bigmodel.cn/api/paas/v4/images/generations"
    )
    assert (
        _images_url("https://x.example.com/v1/images/generations")
        == "https://x.example.com/v1/images/generations"
    )
    with pytest.raises(ValueError, match="Base URL"):
        _images_url("  ")


def test_build_body_defaults():
    body = _build_body({"prompt": "一只猫"}, "cogview-4")
    assert body == {"model": "cogview-4", "prompt": "一只猫", "n": 1}


def test_build_body_style_suffix_appended():
    body = _build_body({"prompt": "一只猫", "style_preset": "transparent_sprite"}, "m")
    assert body["prompt"].startswith("一只猫，")
    assert "白色纯色背景" in body["prompt"]


def test_build_body_size_modes():
    body = _build_body({"prompt": "x", "size": "1024x1792"}, "m")
    assert body["size"] == "1024x1792"
    body = _build_body({"prompt": "x", "size": "custom", "custom_width": 512, "custom_height": 768}, "m")
    assert body["size"] == "512x768"
    with pytest.raises(ValueError, match="宽和高"):
        _build_body({"prompt": "x", "size": "custom", "custom_width": 0}, "m")
    assert "size" not in _build_body({"prompt": "x"}, "m")


def test_build_body_count_clamped():
    assert _build_body({"prompt": "x", "count": 9}, "m")["n"] == 4
    assert _build_body({"prompt": "x", "count": 0}, "m")["n"] == 1
    assert _build_body({"prompt": "x", "count": "abc"}, "m")["n"] == 1


def test_build_body_optional_params():
    body = _build_body(
        {"prompt": "x", "negative_prompt": "模糊", "seed": 42, "extra_params": '{"steps": 30}'},
        "m",
    )
    assert body["negative_prompt"] == "模糊"
    assert body["seed"] == 42
    assert body["steps"] == 30
    # 额外参数不能覆盖模型与提示词
    body = _build_body({"prompt": "x", "extra_params": '{"model": "evil", "prompt": "evil"}'}, "m")
    assert body["model"] == "m"
    assert body["prompt"] == "x"


def test_build_body_validations():
    with pytest.raises(ValueError, match="提示词"):
        _build_body({}, "m")
    with pytest.raises(ValueError, match="JSON"):
        _build_body({"prompt": "x", "extra_params": "{bad"}, "m")
    with pytest.raises(ValueError, match="JSON 对象"):
        _build_body({"prompt": "x", "extra_params": "[1,2]"}, "m")


def _fake_response(items: list[dict]) -> dict:
    return {"data": items}


def test_handler_saves_base64_images(image_env, tmp_path):
    payload = _fake_response(
        [{"b64_json": base64.b64encode(b"img-one").decode()}, {"b64_json": base64.b64encode(b"img-two").decode()}]
    )
    captured = {}

    def fake_request(url, headers, body, timeout_s):
        captured.update(url=url, headers=headers, body=body)
        return payload

    monkey_host = pytest.MonkeyPatch()
    monkey_host.setattr(image_generate, "_request_images", fake_request)
    try:
        result = handler(
            {
                "prompt": "一只猫",
                "count": 2,
                "save_path": str(image_env / "out"),
                "filename_mode": "fixed",
            },
            None,
        )
    finally:
        monkey_host.undo()

    assert captured["url"] == "https://api.openai.com/v1/images/generations"
    assert captured["headers"]["Authorization"] == "Bearer sk-chat"
    assert captured["body"]["model"] == "dall-e-3"
    assert len(result["paths"]) == 2
    assert result["count"] == 2
    assert result["first_path"] == result["paths"][0]
    for i, p in enumerate(result["paths"]):
        assert (image_env / "out" / f"gen_{i + 1}.png").read_bytes() == (b"img-one" if i == 0 else b"img-two")


def test_handler_downloads_url_images(image_env, tmp_path):
    url = "https://cdn.example.com/img.png"
    monkey_host = pytest.MonkeyPatch()
    monkey_host.setattr(
        image_generate, "_request_images", lambda *a, **k: _fake_response([{"url": url}])
    )
    monkey_host.setattr(
        image_generate, "_download_bytes", lambda u, t: b"downloaded" if u == url else b""
    )
    try:
        result = handler(
            {"prompt": "一只猫", "save_path": str(tmp_path / "cat.png"), "filename_mode": "fixed"},
            None,
        )
    finally:
        monkey_host.undo()
    assert result["count"] == 1
    assert (tmp_path / "cat.png").read_bytes() == b"downloaded"


def test_handler_propagates_vendor_error(image_env):
    class _Resp:
        status_code = 400
        content = b"{}"

        def json(self):
            return {"error": {"message": "余额不足"}}

    import httpx

    def fail_post(*a, **k):
        return _Resp()

    monkey_host = pytest.MonkeyPatch()
    monkey_host.setattr(httpx, "post", fail_post)
    try:
        with pytest.raises(ValueError, match="余额不足"):
            handler({"prompt": "一只猫"}, None)
    finally:
        monkey_host.undo()


def test_handler_requires_image_model(image_env, monkeypatch):
    from backend.core.ai.config import set_ai_config

    set_ai_config({"image_model": ""})
    with pytest.raises(ValueError, match="生图模型"):
        handler({"prompt": "一只猫"}, None)


def test_schema_registered():
    from backend.core.registry import register_block

    register_block(image_generate.SCHEMA, handler)


# ---------- 文件命名：默认不覆盖 ----------


def test_resolve_output_target_timestamp_never_overwrites(tmp_path):
    ts = "20260901_143000"
    first = _resolve_output_target(
        str(tmp_path), 0, 1, filename_mode="timestamp", timestamp=ts
    )
    first.write_bytes(b"a")
    again = _resolve_output_target(
        str(tmp_path), 0, 1, filename_mode="timestamp", timestamp=ts
    )
    assert again != first
    assert not again.exists()
    # 固定命名模式保留旧行为：直接覆盖
    fixed = _resolve_output_target(
        str(tmp_path), 0, 1, filename_mode="fixed", timestamp=ts
    )
    assert fixed.name == "gen_1.png"


def test_resolve_output_target_file_save_path_timestamp(tmp_path):
    ts = "20260901_143000"
    out = _resolve_output_target(
        str(tmp_path / "cat.png"), 0, 1, filename_mode="timestamp", timestamp=ts
    )
    assert out.name == f"cat_{ts}.png"
    multi = _resolve_output_target(
        str(tmp_path / "cat.png"), 1, 3, filename_mode="timestamp", timestamp=ts
    )
    assert multi.name == f"cat_{ts}_2.png"


def test_handler_default_naming_keeps_history(image_env, tmp_path):
    payload = _fake_response([{"b64_json": base64.b64encode(b"v1").decode()}])
    monkey_host = pytest.MonkeyPatch()
    monkey_host.setattr(image_generate, "_request_images", lambda *a, **k: payload)
    try:
        r1 = handler({"prompt": "x", "save_path": str(tmp_path / "out")}, None)
        r2 = handler({"prompt": "x", "save_path": str(tmp_path / "out")}, None)
    finally:
        monkey_host.undo()
    assert r1["first_path"] != r2["first_path"]
    assert Path(r1["first_path"]).read_bytes() == b"v1"
    assert Path(r2["first_path"]).read_bytes() == b"v1"


# ---------- 图片编辑（图生图） ----------


def test_images_edit_url_variants():
    assert _images_edit_url("https://api.openai.com/v1") == "https://api.openai.com/v1/images/edits"
    assert (
        _images_edit_url("https://x.example.com/v1/images/edits")
        == "https://x.example.com/v1/images/edits"
    )


def test_build_edit_form_fields():
    form = _build_edit_form(
        {
            "prompt": "把背景改成夜晚",
            "count": 2,
            "size": "1024x1024",
            "seed": 7,
            "extra_params": '{"quality": "high"}',
        },
        "gpt-image-1",
    )
    assert form["model"] == "gpt-image-1"
    assert form["prompt"] == "把背景改成夜晚"
    assert form["n"] == "2"
    assert form["size"] == "1024x1024"
    assert form["seed"] == "7"
    assert form["quality"] == "high"
    with pytest.raises(ValueError, match="提示词"):
        _build_edit_form({}, "m")


def test_load_source_image_local_and_data_url(tmp_path):
    img = tmp_path / "src.png"
    img.write_bytes(b"local-bytes")
    data, name, mime = image_generate._load_source_image(str(img), 10)
    assert (data, name, mime) == (b"local-bytes", "src.png", "image/png")

    b64 = base64.b64encode(b"inline").decode()
    data, name, mime = image_generate._load_source_image(
        f"data:image/jpeg;base64,{b64}", 10
    )
    assert (data, mime) == (b"inline", "image/jpeg")

    with pytest.raises(ValueError, match="参考图不存在"):
        image_generate._load_source_image(str(tmp_path / "missing.png"), 10)


def test_handler_img2img_uses_multipart(image_env, tmp_path):
    src = tmp_path / "src.png"
    src.write_bytes(b"src-bytes")
    captured = {}

    def fake_edits(url, headers, form, image, timeout_s):
        captured.update(url=url, headers=headers, form=form, image=image)
        return _fake_response([{"b64_json": base64.b64encode(b"edited").decode()}])

    monkey_host = pytest.MonkeyPatch()
    monkey_host.setattr(image_generate, "_request_image_edits", fake_edits)
    try:
        result = handler(
            {
                "mode": "img2img",
                "prompt": "把背景换成雪地",
                "source_image": str(src),
                "save_path": str(tmp_path / "out"),
            },
            None,
        )
    finally:
        monkey_host.undo()

    assert captured["url"] == "https://api.openai.com/v1/images/edits"
    assert "Content-Type" not in captured["headers"]
    assert captured["form"]["model"] == "dall-e-3"
    data, name, mime = captured["image"]
    assert (data, name, mime) == (b"src-bytes", "src.png", "image/png")
    assert result["count"] == 1
    assert (tmp_path / "out").exists()


# ---------- 下载与请求：瞬态 SSL 断流自动重试 ----------


class _FakeResp:
    def __init__(self, status_code: int, content: bytes = b""):
        self.status_code = status_code
        self.content = content


@pytest.fixture
def no_retry_sleep(monkeypatch):
    from backend.core.ai import retry as retry_mod

    monkeypatch.setattr(retry_mod.time, "sleep", lambda *_: None)


def test_download_bytes_retries_ssl_eof(no_retry_sleep, monkeypatch):
    calls = {"n": 0}
    kwargs_seen = {}

    def flaky_get(url, **kwargs):
        calls["n"] += 1
        kwargs_seen.update(kwargs)
        if calls["n"] < 3:
            raise httpx.ReadError(
                "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)"
            )
        return _FakeResp(200, b"img")

    monkeypatch.setattr(httpx, "get", flaky_get)
    assert image_generate._download_bytes("https://cdn.example.com/a.png", 10) == b"img"
    assert calls["n"] == 3
    assert "Mozilla/5.0" in kwargs_seen["headers"]["User-Agent"]
    assert kwargs_seen["follow_redirects"] is True


def test_download_bytes_retries_5xx(no_retry_sleep, monkeypatch):
    responses = iter([_FakeResp(503), _FakeResp(503), _FakeResp(200, b"img")])
    calls = {"n": 0}

    def flaky_get(url, **kwargs):
        calls["n"] += 1
        return next(responses)

    monkeypatch.setattr(httpx, "get", flaky_get)
    assert image_generate._download_bytes("https://cdn.example.com/a.png", 10) == b"img"
    assert calls["n"] == 3


def test_download_bytes_no_retry_on_404(no_retry_sleep, monkeypatch):
    calls = {"n": 0}

    def not_found(url, **kwargs):
        calls["n"] += 1
        return _FakeResp(404)

    monkeypatch.setattr(httpx, "get", not_found)
    with pytest.raises(ValueError, match="HTTP 404"):
        image_generate._download_bytes("https://cdn.example.com/gone.png", 10)
    assert calls["n"] == 1


def test_load_source_image_url_error_message(no_retry_sleep, monkeypatch):
    # 参考图为 URL 时，报错文案应是"参考图"而非误导性的"生成图片"
    def refused(url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", refused)
    with pytest.raises(ValueError, match="下载参考图失败"):
        image_generate._load_source_image("https://cdn.example.com/src.png", 10)


def test_request_images_retries_transient(no_retry_sleep, monkeypatch):
    calls = {"n": 0}

    class _OkResp:
        status_code = 200

        def json(self):
            return {"data": [{"b64_json": "x"}]}

    def flaky_post(url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadError("Connection reset by peer")
        return _OkResp()

    monkeypatch.setattr(httpx, "post", flaky_post)
    payload = image_generate._request_images(
        "https://api.example.com/v1/images/generations", {}, {"model": "m", "prompt": "x"}, 10
    )
    assert payload["data"][0]["b64_json"] == "x"
    assert calls["n"] == 2
