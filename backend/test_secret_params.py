"""secret_params：加密往返、防篡改、按 SCHEMA 声明的流程级加解密、幂等。"""

from __future__ import annotations

import base64

import pytest

from backend.core.registry import BLOCK_REGISTRY, register_all_blocks, register_block
from backend.core.secret_params import (
    SECRET_PREFIX,
    decrypt_node_params,
    decrypt_secret,
    decrypt_secret_or_error,
    encrypt_flow_secrets,
    encrypt_secret,
    is_encrypted,
)


@pytest.fixture(autouse=True)
def _blocks_and_key(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUZ_DATA_DIR", str(tmp_path / "nxdata"))  # 独立密钥文件
    if "smtp_send" not in BLOCK_REGISTRY:
        register_all_blocks()
    yield


def test_roundtrip_unicode():
    for raw in ("secret-pass", "中文密码✓", "a" * 500, "with:colons and = signs"):
        enc = encrypt_secret(raw)
        assert is_encrypted(enc)
        assert not enc.count(raw), "密文不应含明文片段"
        assert decrypt_secret(enc) == raw


def test_tamper_detected():
    enc = encrypt_secret("secret-pass")
    body, mac = enc[len(SECRET_PREFIX):].rsplit(":", 1)
    raw_payload = bytearray(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    raw_payload[0] ^= 0x01  # 翻转密文一字节
    tampered = (
        SECRET_PREFIX
        + base64.urlsafe_b64encode(bytes(raw_payload)).rstrip(b"=").decode()
        + ":"
        + mac
    )
    with pytest.raises(ValueError):
        decrypt_secret(tampered)


def test_wrong_machine_key_cannot_decrypt(monkeypatch, tmp_path):
    enc = encrypt_secret("secret-pass")
    monkeypatch.setenv("NEXUZ_DATA_DIR", str(tmp_path / "other-machine"))  # 换密钥
    with pytest.raises(ValueError):
        decrypt_secret(enc)
    with pytest.raises(ValueError, match="重新填写"):
        decrypt_secret_or_error(enc, param_name="password")


def test_key_file_stable_across_reloads():
    """密钥文件跨调用（模拟进程重启）稳定：反复读写不漂移。"""
    from backend.core.secret_params import _load_key, secrets_key_path

    enc = encrypt_secret("稳定性")
    k1 = _load_key()
    k2 = _load_key()  # 重新读文件
    assert k1 == k2 and len(k1) == 32
    # 即使 key 文件恰含任何字节序列也不受 strip 类问题影响（hex 文本存储）
    raw = secrets_key_path().read_text(encoding="ascii")
    assert bytes.fromhex(raw.strip()) == k1
    assert decrypt_secret(enc) == "稳定性"


def test_encrypt_flow_secrets_only_secret_inputs():
    flow = {
        "name": "邮件",
        "nodes": {
            "a": {
                "type": "smtp_send",
                "params": {
                    "host": "smtp.test",
                    "password": "plain-secret",
                    "subject": "主题",
                },
            },
            "b": {"type": "http_request", "params": {"url": "https://x", "password": "not-secret"}},
        },
        "entry": "a",
    }
    out = encrypt_flow_secrets(flow)
    a = out["nodes"]["a"]["params"]
    b = out["nodes"]["b"]["params"]
    assert is_encrypted(a["password"]) and decrypt_secret(a["password"]) == "plain-secret"
    assert a["host"] == "smtp.test" and a["subject"] == "主题"  # 非 secret 原样
    assert b["password"] == "not-secret"  # http_request 未声明 secret


def test_encrypt_idempotent():
    flow = {"nodes": {"a": {"type": "smtp_send", "params": {"password": "pw"}}}, "entry": "a"}
    once = encrypt_flow_secrets(flow)
    first = once["nodes"]["a"]["params"]["password"]
    twice = encrypt_flow_secrets(once)
    assert twice["nodes"]["a"]["params"]["password"] == first  # 已加密值原样保留


def test_decrypt_node_params_passthrough_and_error():
    enc = encrypt_secret("pw")
    out = decrypt_node_params("smtp_send", {"password": enc, "host": "smtp.test"})
    assert out["password"] == "pw" and out["host"] == "smtp.test"
    # 明文（如来自 env_var 绑定）原样透传
    out = decrypt_node_params("smtp_send", {"password": "from-env", "host": "x"})
    assert out["password"] == "from-env"
    # 未注册类型：不变
    assert decrypt_node_params("no_such", {"password": enc})["password"] == enc
    # 错误密文 → 可读报错
    with pytest.raises(ValueError, match="password"):
        decrypt_node_params("smtp_send", {"password": SECRET_PREFIX + "bad:mac"})


def test_smtp_send_registered_and_gated():
    schema = (BLOCK_REGISTRY.get("smtp_send") or {}).get("schema") or {}
    assert schema.get("type") == "smtp_send"
    assert not schema.get("requires")  # A 档：服务器可用
    inputs = {i["name"]: i for i in schema["inputs"]}
    assert inputs["password"].get("secret") is True

    from backend.core.execution_policy import ELEVATED_TYPES

    assert "smtp_send" in ELEVATED_TYPES
    from backend.core.ai.run_block import classify_run_block

    assert classify_run_block("smtp_send") == "action"
