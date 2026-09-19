"""SMTP 代发邮件：用自己的邮箱（QQ/163/企业邮箱 SMTP + 授权码）发信。

- 纯 stdlib（smtplib + email），零新依赖，Windows / Linux 服务器通用（A 档）；
- 密码参数声明 "secret": true——保存流程时落盘即密文（backend/core/secret_params），
  运行时解密，日志/AI refine 不见明文；也可绑定 {{env_var 节点.值}} 等变量；
- 收件人支持逗号/分号/换行分隔多个，也可绑定上游数组输出；
- 附件接 split_input_paths 多输入归一化，可直接绑定流程产物路径；
- 网络副作用：执行策略归 ELEVATED（同 http_request）——safe 模式拦截，
  用户自跑零拦截，外部 AI 双闸。
"""

from __future__ import annotations

import re
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from backend.blocks._helpers import split_input_paths

SCHEMA = {
    "type": "smtp_send",
    "description": "用自备 SMTP 邮箱发送邮件（支持多收件人/抄送/附件/HTML）。密码为授权码，落盘自动加密。",
    "label": "发送邮件",
    "category": "系统类",
    "inputs": [
        {
            "name": "host",
            "type": "string",
            "label": "SMTP 服务器",
            "default": "",
            "placeholder": "如 smtp.qq.com / smtp.163.com / smtp.office365.com",
            "bindable": True,
            "required": True,
        },
        {
            "name": "port",
            "type": "number",
            "label": "端口",
            "default": 465,
            "placeholder": "SSL=465，STARTTLS=587",
        },
        {
            "name": "security",
            "type": "select",
            "label": "加密方式",
            "options": ["ssl", "starttls"],
            "default": "ssl",
            "option_labels": {"ssl": "SSL/TLS（465）", "starttls": "STARTTLS（587）"},
        },
        {
            "name": "username",
            "type": "string",
            "label": "登录账号",
            "default": "",
            "placeholder": "通常是完整邮箱地址",
            "bindable": True,
            "required": True,
        },
        {
            "name": "password",
            "type": "string",
            "ui": "password",
            "label": "授权码/密码",
            "default": "",
            "placeholder": "邮箱设置里生成的 SMTP 授权码（非登录密码）；保存流程时自动加密",
            "bindable": True,
            "required": True,
            "secret": True,
        },
        {
            "name": "sender",
            "type": "string",
            "label": "发件人",
            "default": "",
            "placeholder": "留空用登录账号",
            "bindable": True,
        },
        {
            "name": "to_list",
            "type": "string",
            "ui": "textarea",
            "label": "收件人",
            "default": "",
            "placeholder": "逗号/分号/换行分隔多个，如 a@x.com, b@y.com",
            "bindable": True,
            "required": True,
        },
        {
            "name": "cc_list",
            "type": "string",
            "ui": "textarea",
            "label": "抄送",
            "default": "",
            "placeholder": "可留空",
            "bindable": True,
        },
        {
            "name": "subject",
            "type": "string",
            "label": "主题",
            "default": "",
            "bindable": True,
            "required": True,
        },
        {
            "name": "body",
            "type": "string",
            "ui": "textarea",
            "label": "正文",
            "default": "",
            "placeholder": "支持 {{变量}} 拼接上游输出",
            "bindable": True,
            "required": True,
        },
        {
            "name": "body_format",
            "type": "select",
            "label": "正文格式",
            "options": ["text", "html"],
            "default": "text",
            "option_labels": {"text": "纯文本", "html": "HTML"},
        },
        {
            "name": "attachments",
            "type": "string",
            "ui": "textarea",
            "label": "附件路径",
            "default": "",
            "placeholder": "一行一个或逗号分隔；可绑定 {{节点.path}} 列表",
            "bindable": True,
        },
        {
            "name": "timeout_sec",
            "type": "number",
            "label": "超时秒数",
            "default": 30,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "accepted", "type": "number"},
        {"name": "refused", "type": "object", "canvas": False},
        {"name": "error", "type": "string"},
    ],
}

_EMAIL_SPLIT = re.compile(r"[,;，；\s]+")


def _parse_addresses(raw: object) -> list[str]:
    """收件人/抄送归一化：分隔符切分 + 去重保序；也接受绑定来的 list。"""
    if isinstance(raw, (list, tuple)):
        items = [str(x) for x in raw]
    else:
        items = _EMAIL_SPLIT.split(str(raw or ""))
    out: list[str] = []
    for item in items:
        addr = item.strip().strip("<>")
        if addr and addr not in out:
            out.append(addr)
    return out


def handler(params, context, **kwargs):
    import smtplib
    import ssl as ssl_mod

    host = str(params.get("host") or "").strip()
    username = str(params.get("username") or "").strip()
    password = str(params.get("password") or "")
    if not host or not username:
        return {"ok": False, "accepted": 0, "refused": {}, "error": "缺少 SMTP 服务器或登录账号"}
    if not password:
        return {"ok": False, "accepted": 0, "refused": {}, "error": "缺少授权码/密码"}

    to_addrs = _parse_addresses(params.get("to_list"))
    if not to_addrs:
        return {"ok": False, "accepted": 0, "refused": {}, "error": "缺少收件人"}
    cc_addrs = _parse_addresses(params.get("cc_list"))
    sender = str(params.get("sender") or "").strip() or username
    subject = str(params.get("subject") or "")
    body = str(params.get("body") or "")
    body_format = str(params.get("body_format") or "text").strip().lower()
    try:
        port = int(params.get("port") or 465)
    except (TypeError, ValueError):
        port = 465
    try:
        timeout = float(params.get("timeout_sec") or 30)
    except (TypeError, ValueError):
        timeout = 30.0

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to_addrs)
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1] if "@" in sender else "nexuz")
    if body_format == "html":
        msg.set_content("（需支持 HTML 的客户端查看）")
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)

    attachment_paths = split_input_paths(params.get("attachments"))
    for path in attachment_paths:
        try:
            data = path.read_bytes()
        except OSError as exc:
            return {"ok": False, "accepted": 0, "refused": {}, "error": f"附件读取失败 {path.name}: {exc}"}
        maintype, subtype = ("application", "octet-stream")
        guessed = mimetypes_guess(str(path))
        if guessed and "/" in guessed:
            maintype, subtype = guessed.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=path.name)

    security = str(params.get("security") or "ssl").strip().lower()
    try:
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=timeout)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
            server.starttls(context=ssl_mod.create_default_context())
        try:
            server.login(username, password)
            refused = server.send_message(msg, from_addr=sender, to_addrs=to_addrs + cc_addrs)
        finally:
            try:
                server.quit()
            except Exception:
                pass
        accepted = len(to_addrs) + len(cc_addrs) - len(refused or {})
        return {
            "ok": True,
            "accepted": int(accepted),
            "refused": dict(refused or {}),
            "error": "",
        }
    except smtplib.SMTPAuthenticationError as exc:
        return {"ok": False, "accepted": 0, "refused": {}, "error": f"SMTP 认证失败（检查授权码）: {exc}"}
    except (smtplib.SMTPException, OSError) as exc:
        return {"ok": False, "accepted": 0, "refused": {}, "error": f"SMTP 发送失败: {exc}"}


def mimetypes_guess(path: str) -> str | None:
    import mimetypes

    return mimetypes.guess_type(path)[0]
