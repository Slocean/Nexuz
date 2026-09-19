"""smtp_send：手搭迷你 SMTP 服务器实测收发（附件/HTML/多收件人/拒收），
以及"保存流程密文落盘 → 解释器运行解密 → 日志无明文"全链路。"""

from __future__ import annotations

import base64
import json
import socket
import threading
from pathlib import Path

import pytest

from backend.blocks.smtp_send import _parse_addresses, handler as smtp_handler


# ---------------------------------------------------------------------------
# 迷你 SMTP 服务器（stdlib socket，仅够 smtplib 客户端对话）
# ---------------------------------------------------------------------------

class MiniSMTPServer:
    def __init__(self, *, refuse: set[str] | None = None):
        self.refuse = refuse or set()
        self.messages: list[dict] = []  # {mail_from, rcpt_tos, data, auth_plain}
        self._stop = threading.Event()
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        self._sock.settimeout(0.3)
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            threading.Thread(target=self._talk, args=(conn,), daemon=True).start()

    def _talk(self, conn: socket.socket) -> None:
        rec = {"mail_from": "", "rcpt_tos": [], "data": "", "auth_plain": ""}
        f = conn.makefile("rb")
        conn.sendall(b"220 mini.test ESMTP\r\n")
        while True:
            line = f.readline()
            if not line:
                break
            cmd = line.decode("utf-8", "replace").rstrip("\r\n")
            upper = cmd.upper()
            if upper.startswith("EHLO"):
                conn.sendall(b"250-mini.test\r\n250-AUTH PLAIN LOGIN\r\n250 SMTPUTF8\r\n")
            elif upper.startswith("HELO"):
                conn.sendall(b"250 mini.test\r\n")
            elif upper.startswith("AUTH PLAIN"):
                # 取 "AUTH PLAIN " 之后的 b64 token（P/L/A/I/N 都是合法 b64 字符，
                # 多切一个词会被 b64decode 静默吞掉产生乱码）
                rec["auth_plain"] = cmd.split(" ", 2)[2] if " " in cmd else ""
                conn.sendall(b"235 ok\r\n")
            elif upper.startswith("AUTH"):
                conn.sendall(b"235 ok\r\n")
            elif upper.startswith("MAIL FROM"):
                rec["mail_from"] = cmd
                conn.sendall(b"250 ok\r\n")
            elif upper.startswith("RCPT TO"):
                if any(r in cmd for r in self.refuse):
                    conn.sendall(b"550 no such user\r\n")
                else:
                    rec["rcpt_tos"].append(cmd)
                    conn.sendall(b"250 ok\r\n")
            elif upper.startswith("DATA"):
                conn.sendall(b"354 end with <CRLF>.<CRLF>\r\n")
                body: list[str] = []
                while True:
                    dl = f.readline()
                    if not dl:
                        break
                    if dl in (b".\r\n", b".\n"):
                        break
                    body.append(dl.decode("utf-8", "replace"))
                rec["data"] = "".join(body)
                conn.sendall(b"250 ok\r\n")
                self.messages.append(rec)
                rec = {"mail_from": "", "rcpt_tos": [], "data": "", "auth_plain": ""}
            elif upper.startswith("QUIT"):
                conn.sendall(b"221 bye\r\n")
                break
            elif upper.startswith("RSET") or upper.startswith("NOOP"):
                conn.sendall(b"250 ok\r\n")
            else:
                conn.sendall(b"250 ok\r\n")
        try:
            conn.close()
        except OSError:
            pass

    def close(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass


@pytest.fixture
def smtp_server():
    server = MiniSMTPServer()
    yield server
    server.close()


@pytest.fixture(autouse=True)
def route_tls_to_plain(monkeypatch, smtp_server):
    """无 TLS 测试服务器：把 SSL/STARTTLS 分支路由到明文连接（只验分支逻辑）。"""
    import smtplib

    def fake_ssl(host, port=0, timeout=None, **kw):
        return smtplib.SMTP(host, smtp_server.port, timeout=timeout)

    def fake_starttls(self, **kw):
        return (220, b"ok")

    monkeypatch.setattr(smtplib, "SMTP_SSL", fake_ssl)
    monkeypatch.setattr(smtplib.SMTP, "starttls", fake_starttls)


def send(**overrides) -> dict:
    params = {
        "host": "127.0.0.1",
        "port": smtp_server_fixed_port(),
        "security": "ssl",
        "username": "me@test.com",
        "password": "auth-code-123",
        "to_list": "a@test.com, b@test.com",
        "subject": "测试",
        "body": "正文内容",
        "timeout_sec": 10,
    }
    params.update(overrides)
    return smtp_handler(params, {})


def smtp_server_fixed_port() -> int:
    return _CURRENT_SERVER[0].port


_CURRENT_SERVER: list[MiniSMTPServer] = []


@pytest.fixture(autouse=True)
def _track_current_server(smtp_server):
    _CURRENT_SERVER.clear()
    _CURRENT_SERVER.append(smtp_server)
    yield


# ---------------------------------------------------------------------------
# handler 实测
# ---------------------------------------------------------------------------

def test_send_plain_text_multi_recipients():
    import email
    import email.policy

    out = send()
    assert out["ok"] is True and out["accepted"] == 2 and out["error"] == ""
    rec = _CURRENT_SERVER[0].messages[-1]
    assert "me@test.com" in rec["mail_from"]
    assert len(rec["rcpt_tos"]) == 2
    msg = email.message_from_string(rec["data"], policy=email.policy.default)
    assert msg["Subject"] == "测试"  # 非 ASCII 主题按 RFC 2047 编码，此处解码后断言
    assert msg["From"] == "me@test.com"
    assert msg["To"] == "a@test.com, b@test.com"
    assert "正文内容" in rec["data"]  # 正文为 8bit UTF-8 原文，直接查原始数据
    # AUTH PLAIN 携带解码后的账号与授权码
    decoded = base64.b64decode(rec["auth_plain"]).decode("utf-8", "replace")
    assert "me@test.com" in decoded and "auth-code-123" in decoded


def test_send_html_and_attachments(tmp_path):
    att = tmp_path / "报表.txt"
    att.write_text("attachment-body", encoding="utf-8")
    out = send(body_format="html", body="<b>Hi</b>", attachments=str(att))
    assert out["ok"] is True
    data = _CURRENT_SERVER[0].messages[-1]["data"]
    assert "text/html" in data and "multipart/alternative" in data
    assert "attachment;" in data
    assert base64.b64encode(b"attachment-body").decode() in data


def test_recipient_list_variants():
    assert _parse_addresses("a@x.com, b@x.com；c@x.com\nd@x.com") == [
        "a@x.com", "b@x.com", "c@x.com", "d@x.com",
    ]
    assert _parse_addresses(["a@x.com ", "", "a@x.com"]) == ["a@x.com"]
    out = send(to_list=["list@x.com"], cc_list="cc@x.com")
    assert out["accepted"] == 2
    data = _CURRENT_SERVER[0].messages[-1]["data"]
    assert "Cc: cc@x.com" in data


def test_partial_refusal_counts():
    refusing = MiniSMTPServer(refuse={"gone@test.com"})
    _CURRENT_SERVER[0] = refusing
    try:
        out = send(to_list="ok@test.com, gone@test.com", security="starttls")
        assert out["ok"] is True and out["accepted"] == 1
        assert out["refused"] and "gone@test.com" in str(out["refused"])
    finally:
        refusing.close()


def test_param_errors():
    assert "缺少 SMTP 服务器或登录账号" in send(host="")["error"]
    assert "缺少授权码/密码" in send(password="")["error"]
    assert "缺少收件人" in send(to_list="")["error"]
    missing = send(attachments=r"Z:\nope\不存在的文件.txt")
    assert missing["ok"] is False and "附件读取失败" in missing["error"]


# ---------------------------------------------------------------------------
# 全链路：保存流程密文落盘 → 解释器运行解密 → 日志无明文
# ---------------------------------------------------------------------------

def _make_flow() -> dict:
    return {
        "flow_id": "smtp-e2e",
        "name": "邮件流程",
        "nodes": {
            "a": {
                "type": "smtp_send",
                "params": {
                    "host": "127.0.0.1",
                    "port": smtp_server_fixed_port(),
                    "security": "ssl",
                    "username": "flow@test.com",
                    "password": "flow-secret-pw",
                    "to_list": "dest@test.com",
                    "subject": "流程邮件",
                    "body": "来自流程",
                },
                "next": None,
            }
        },
        "entry": "a",
    }


def test_flow_save_encrypts_and_run_decrypts(monkeypatch, tmp_path, smtp_server):
    monkeypatch.setenv("NEXUZ_DATA_DIR", str(tmp_path / "nxdata"))
    from backend.core.host_mode import set_headless
    from backend.core.registry import BLOCK_REGISTRY, register_all_blocks
    from backend.server import ServerApi

    set_headless(True)  # 服务器形态同样可用（A 档）
    if "smtp_send" not in BLOCK_REGISTRY:
        register_all_blocks()
    try:
        api = ServerApi()
        saved = api.save_flow(json.dumps(_make_flow()))
        assert saved["ok"] is True

        raw = Path(saved["path"]).read_text(encoding="utf-8")
        assert "enc:v1:" in raw
        assert "flow-secret-pw" not in raw  # 明文绝不落盘

        loaded = api.load_flow(saved["path"])
        assert loaded["ok"] is True
        out = api.run_flow(loaded["flow"])
        assert out["ok"] is True and out["started"] is True
        from backend.core.interpreter import get_interpreter

        get_interpreter().wait_until_idle(timeout=20)

        # 邮件确实发出，且用的是解密后的密码
        rec = smtp_server.messages[-1]
        decoded = base64.b64decode(rec["auth_plain"]).decode("utf-8", "replace")
        assert "flow@test.com" in decoded and "flow-secret-pw" in decoded

        # 运行日志不落明文（node_start 事件在解密前发出）
        logs = "\n".join(
            p.read_text(encoding="utf-8", errors="ignore")
            for p in (tmp_path / "nxdata" / "logs").rglob("*.jsonl")
        )
        assert "flow-secret-pw" not in logs
    finally:
        set_headless(False)
