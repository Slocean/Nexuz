"""流程参数静态加密（secret inputs）：SMTP 授权码等敏感参数落盘即密文。

设计：
- SCHEMA 的 inputs 可声明 "secret": true（如 smtp_send.password）；保存路径
  （Api.save_flow / save_flow_template / ServerApi.save_flow）把对应参数值
  加密为 "enc:v1:…" 常量，运行路径（interpreter / run_block_once）在 handler
  调用前解密——运行日志、AI refine、MCP 目录看到的都是密文。
- 密钥：机器本机文件 data_dir/secrets.key（首次使用自动生成 32 字节随机数，
  POSIX 上收紧权限）。流程文件会经 git/scp 同步，密钥文件不同步——跨机器
  拿到流程也解不开；密钥泄露面与本机 config.json 相同。
- 算法（纯 stdlib，无新依赖）：HMAC-SHA256 派生加解密子密钥；密钥流 =
  HMAC(k_enc, nonce‖counter) CTR 模式；encrypt-then-MAC（k_mac 覆盖 nonce+ct），
  tag 恒时比较。非 Windows 与 Windows 同一套实现（跨平台一致，测试可覆盖）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets as pysecrets
from pathlib import Path
from typing import Any

SECRET_PREFIX = "enc:v1:"
_NONCE_BYTES = 16
_MAC_BYTES = 32


# ---------------------------------------------------------------------------
# 密钥文件
# ---------------------------------------------------------------------------

def secrets_key_path() -> Path:
    from backend.paths import get_data_dir

    return get_data_dir() / "secrets.key"


def _load_key() -> bytes:
    """密钥以 hex 文本存取——绝不能按原始字节 strip（随机字节含空白时会被
    截断，长度不足即触发重新生成，加解密用上不同密钥，解密得到乱码）。"""
    path = secrets_key_path()
    try:
        key = bytes.fromhex(path.read_text(encoding="ascii").strip())
        if len(key) == 32:
            return key
    except (OSError, ValueError):
        pass
    key = pysecrets.token_bytes(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key.hex(), encoding="ascii")
    try:
        os.chmod(path, 0o600)  # POSIX；Windows 忽略失败
    except OSError:
        pass
    return key


def _subkeys() -> tuple[bytes, bytes]:
    key = _load_key()
    k_enc = hmac.new(key, b"nexuz-secret-enc", hashlib.sha256).digest()
    k_mac = hmac.new(key, b"nexuz-secret-mac", hashlib.sha256).digest()
    return k_enc, k_mac


# ---------------------------------------------------------------------------
# 单值加解密
# ---------------------------------------------------------------------------

def is_encrypted(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(SECRET_PREFIX)


def _keystream(k_enc: bytes, nonce: bytes, length: int) -> bytes:
    blocks = []
    counter = 0
    while sum(len(b) for b in blocks) < length:
        blocks.append(
            hmac.new(k_enc, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        )
        counter += 1
    return b"".join(blocks)[:length]


def encrypt_secret(value: str) -> str:
    raw = str(value).encode("utf-8")
    k_enc, k_mac = _subkeys()
    nonce = pysecrets.token_bytes(_NONCE_BYTES)
    ct = bytes(a ^ b for a, b in zip(raw, _keystream(k_enc, nonce, len(raw))))
    tag = hmac.new(k_mac, nonce + ct, hashlib.sha256).digest()
    payload = base64.urlsafe_b64encode(nonce + ct).rstrip(b"=").decode("ascii")
    mac = base64.urlsafe_b64encode(tag).rstrip(b"=").decode("ascii")
    return f"{SECRET_PREFIX}{payload}:{mac}"


def decrypt_secret(value: str) -> str:
    if not is_encrypted(value):
        return str(value)
    try:
        body = value[len(SECRET_PREFIX):]
        payload_b64, mac_b64 = body.rsplit(":", 1)
        pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        nonce_ct = base64.urlsafe_b64decode(pad(payload_b64))
        tag = base64.urlsafe_b64decode(pad(mac_b64))
        if len(nonce_ct) < _NONCE_BYTES + 1:
            raise ValueError("payload too short")
        nonce, ct = nonce_ct[:_NONCE_BYTES], nonce_ct[_NONCE_BYTES:]
        k_enc, k_mac = _subkeys()
        expect = hmac.new(k_mac, nonce + ct, hashlib.sha256).digest()
        if not hmac.compare_digest(expect, tag):
            raise ValueError("mac mismatch")
        raw = bytes(a ^ b for a, b in zip(ct, _keystream(k_enc, nonce, len(ct))))
        return raw.decode("utf-8")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"敏感参数解密失败: {exc}") from exc


def decrypt_secret_or_error(value: str, *, param_name: str) -> str:
    """解密失败转成可读错误（密钥文件被删/换机器 → 提示重新填写）。"""
    try:
        return decrypt_secret(value)
    except ValueError as exc:
        raise ValueError(
            f"参数 {param_name} 为加密值但本机密钥无法解密（{exc}）。"
            "可能是流程从别的机器同步而来——请在本机重新填写该参数。"
        ) from exc


# ---------------------------------------------------------------------------
# 流程级：按 SCHEMA secret 声明加解密
# ---------------------------------------------------------------------------

def _secret_param_names(block_type: str) -> set[str]:
    from backend.core.registry import BLOCK_REGISTRY

    entry = BLOCK_REGISTRY.get(block_type)
    schema = entry.get("schema") if isinstance(entry, dict) else None
    if not isinstance(schema, dict):
        return set()
    return {
        str(inp.get("name"))
        for inp in (schema.get("inputs") or [])
        if isinstance(inp, dict) and inp.get("secret") and inp.get("name")
    }


def encrypt_flow_secrets(flow: dict[str, Any]) -> dict[str, Any]:
    """保存前调用：把流程内所有声明为 secret 且尚未加密的参数加密（幂等）。"""
    nodes = flow.get("nodes")
    if not isinstance(nodes, dict):
        return flow
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        params = node.get("params")
        if not isinstance(params, dict):
            continue
        for name in _secret_param_names(str(node.get("type") or "")):
            value = params.get(name)
            if isinstance(value, str) and value and not is_encrypted(value):
                params[name] = encrypt_secret(value)
    return flow


def decrypt_node_params(block_type: str, params: dict[str, Any]) -> dict[str, Any]:
    """handler 调用前调用：解密已加密的 secret 参数；其余原样透传。

    返回浅拷贝（不改动调用方的 params）；解密失败抛 ValueError（带参数名）。
    """
    names = _secret_param_names(str(block_type or ""))
    if not names:
        return params
    out = dict(params)
    for name in names:
        value = out.get(name)
        if is_encrypted(value):
            out[name] = decrypt_secret_or_error(str(value), param_name=name)
    return out
