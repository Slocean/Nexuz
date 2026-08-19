from __future__ import annotations

import json
import sys

import pytest

from backend.core.ai.api_key_crypto import (
    is_encrypted,
    protect_api_key,
    unprotect_api_key,
)
from backend.core.ai.config import get_ai_config, public_ai_config, set_ai_config


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr("backend.paths.config_path", lambda: path)
    return path


def test_legacy_plaintext_is_identified():
    assert unprotect_api_key("sk-legacy") == ("sk-legacy", True)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI only")
def test_dpapi_round_trip_does_not_contain_plaintext():
    encrypted = protect_api_key("sk-secret-value")
    assert is_encrypted(encrypted)
    assert "sk-secret-value" not in encrypted
    assert unprotect_api_key(encrypted) == ("sk-secret-value", False)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI only")
def test_set_config_encrypts_active_and_preset_keys(isolated_config):
    set_ai_config(
        {
            "preset": "openai",
            "api_key": "sk-active-secret",
            "options": {
                "deepseek": {
                    "base_url": "https://api.deepseek.com/v1",
                    "api_key": "sk-slot-secret",
                    "model": "deepseek-chat",
                }
            },
        }
    )

    raw_text = isolated_config.read_text(encoding="utf-8")
    assert "sk-active-secret" not in raw_text
    assert "sk-slot-secret" not in raw_text
    raw = json.loads(raw_text)
    assert is_encrypted(raw["ai"]["api_key"])
    assert is_encrypted(raw["ai"]["options"]["deepseek"]["api_key"])
    assert get_ai_config().api_key == "sk-active-secret"

    public = public_ai_config()
    assert "api_key" not in public
    assert public["has_api_key"] is True
    assert public["api_key_masked"].endswith("cret")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI only")
def test_plaintext_config_is_migrated_on_first_read(isolated_config):
    isolated_config.write_text(
        json.dumps(
            {
                "ai": {
                    "preset": "openai",
                    "api_key": "sk-old-secret",
                    "options": {
                        "openai": {
                            "api_key": "sk-old-secret",
                            "base_url": "https://api.openai.com/v1",
                            "model": "gpt-4o-mini",
                        }
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    assert get_ai_config().api_key == "sk-old-secret"
    migrated = isolated_config.read_text(encoding="utf-8")
    assert "sk-old-secret" not in migrated
    assert "dpapi:v1:" in migrated
