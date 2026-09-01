"""生图配置项：image_* 字段持久化、加密、掩码与运行时回退解析。"""

from __future__ import annotations

import json

import pytest

from backend.core.ai.config import get_ai_config, public_ai_config, resolve_image_config, set_ai_config


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr("backend.paths.config_path", lambda: path)
    for name in (
        "NEXUZ_AI_IMAGE_BASE_URL",
        "NEXUZ_AI_IMAGE_API_KEY",
        "NEXUZ_AI_IMAGE_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    return path


def _base_chat(patch: dict | None = None) -> None:
    set_ai_config(
        {
            "preset": "zhipu",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "api_key": "sk-chat-secret",
            "model": "glm-4-flash",
            **(patch or {}),
        }
    )


def test_image_fields_round_trip(isolated_config):
    _base_chat(
        {
            "image_base_url": "https://api.openai.com/v1",
            "image_api_key": "sk-image-secret",
            "image_model": "dall-e-3",
        }
    )
    cfg = get_ai_config()
    assert cfg.image_base_url == "https://api.openai.com/v1"
    assert cfg.image_api_key == "sk-image-secret"
    assert cfg.image_model == "dall-e-3"
    # 聊天配置不受影响
    assert cfg.api_key == "sk-chat-secret"


def test_image_key_is_encrypted_and_masked(isolated_config):
    _base_chat({"image_api_key": "sk-image-secret", "image_model": "dall-e-3"})

    raw = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert "sk-image-secret" not in isolated_config.read_text(encoding="utf-8")

    public = public_ai_config()
    assert "image_api_key" not in public
    assert public["has_image_api_key"] is True
    assert public["image_api_key_masked"].endswith("cret")
    assert "sk-image-secret" not in json.dumps(public, ensure_ascii=False)


def test_empty_image_key_is_kept_on_save(isolated_config):
    _base_chat({"image_api_key": "sk-image-secret", "image_model": "dall-e-3"})
    # 前端保存时 image_api_key 为空 + keep_existing_key=True → 不清空
    set_ai_config({"image_model": "cogview-4"})
    cfg = get_ai_config()
    assert cfg.image_api_key == "sk-image-secret"
    assert cfg.image_model == "cogview-4"


def test_resolve_falls_back_to_chat_provider(isolated_config):
    _base_chat({"image_model": "cogview-4"})
    resolved = resolve_image_config()
    assert resolved["base_url"] == "https://open.bigmodel.cn/api/paas/v4"
    assert resolved["api_key"] == "sk-chat-secret"
    assert resolved["model"] == "cogview-4"


def test_resolve_uses_image_specific_values(isolated_config):
    _base_chat(
        {
            "image_base_url": "https://api.openai.com/v1",
            "image_api_key": "sk-image-secret",
            "image_model": "dall-e-3",
        }
    )
    resolved = resolve_image_config()
    assert resolved == {
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-image-secret",
        "model": "dall-e-3",
    }


def test_resolve_requires_model(isolated_config):
    _base_chat()
    with pytest.raises(ValueError, match="生图模型"):
        resolve_image_config()
