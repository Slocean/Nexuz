from __future__ import annotations

import json
import shlex
import subprocess
from typing import Any

from backend.blocks._system_io import normalize_path

SCHEMA = {
    "type": "run_command",
    "label": "执行命令",
    "category": "系统类",
    "inputs": [
        {
            "name": "command",
            "type": "string",
            "label": "命令",
            "default": "",
            "placeholder": "可执行文件或 shell 命令",
            "ui": "textarea",
            "bindable": True,
        },
        {
            "name": "args",
            "type": "string",
            "label": "参数",
            "default": "",
            "placeholder": '空格分隔，或 JSON 数组如 ["a","b"]',
            "ui": "textarea",
            "bindable": True,
        },
        {
            "name": "cwd",
            "type": "string",
            "label": "工作目录",
            "default": "",
            "bindable": True,
        },
        {
            "name": "timeout_sec",
            "type": "number",
            "label": "超时秒数",
            "default": 60,
        },
        {
            "name": "shell",
            "type": "select",
            "label": "使用 Shell",
            "options": ["false", "true"],
            "default": "false",
            "option_labels": {"false": "否（推荐）", "true": "是"},
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "exit_code", "type": "number"},
        {"name": "stdout", "type": "string"},
        {"name": "stderr", "type": "string"},
        {"name": "error", "type": "string"},
    ],
}


def _parse_args(raw: Any) -> list[str]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    text = str(raw).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except Exception:
            pass
    try:
        return shlex.split(text, posix=False)
    except ValueError:
        return text.split()


def handler(params, context, **kwargs):
    command = str(params.get("command") or "").strip()
    if not command:
        return {
            "ok": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": "",
            "error": "命令不能为空",
        }

    use_shell = str(params.get("shell") or "false").strip().lower() in ("true", "1", "yes")
    arg_list = _parse_args(params.get("args"))

    cwd = None
    cwd_raw = str(params.get("cwd") or "").strip()
    if cwd_raw:
        path, err = normalize_path(cwd_raw)
        if err or path is None:
            return {
                "ok": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": "",
                "error": err or "无效工作目录",
            }
        if not path.is_dir():
            return {
                "ok": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": "",
                "error": f"工作目录不存在: {path}",
            }
        cwd = str(path)

    try:
        timeout = float(params.get("timeout_sec") if params.get("timeout_sec") not in (None, "") else 60)
    except (TypeError, ValueError):
        timeout = 60.0
    timeout = max(1.0, min(3600.0, timeout))

    try:
        if use_shell:
            # Join for shell so users can pass pipelines when shell=true
            full = command if not arg_list else f"{command} {' '.join(arg_list)}"
            completed = subprocess.run(
                full,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        else:
            completed = subprocess.run(
                [command, *arg_list],
                shell=False,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        code = int(completed.returncode)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        ok = code == 0
        return {
            "ok": ok,
            "exit_code": code,
            "stdout": stdout,
            "stderr": stderr,
            "error": "" if ok else (stderr.strip() or f"退出码 {code}"),
        }
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else (
            (exc.stdout or b"").decode("utf-8", errors="replace") if exc.stdout else ""
        )
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else (
            (exc.stderr or b"").decode("utf-8", errors="replace") if exc.stderr else ""
        )
        return {
            "ok": False,
            "exit_code": -1,
            "stdout": stdout,
            "stderr": stderr,
            "error": f"命令超时（{timeout}s）",
        }
    except Exception as exc:
        return {
            "ok": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": "",
            "error": str(exc),
        }
