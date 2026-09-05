"""trusted_worker：隔离执行与文件写入放行策略。

审计钩子不可在进程内卸载，一律通过真实 worker 子进程验证（与生产路径一致）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

_MINI_PLUGIN = '''\\
SCHEMA = {{"type": "{block_type}", "label": "mini", "category": "自定义"}}
from pathlib import Path


def handler(params, context, **kwargs):
    target = Path(params["target"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("done", encoding="utf-8")
    return {{"ok": True, "written": target.exists()}}
'''


def _run_worker(request: dict, extra_env: dict | None = None) -> dict:
    env = dict(os.environ)
    # 与生产 worker_client.run_isolated 一致：显式 UTF-8 IO
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, "-m", "backend.core.trusted_worker"],
        input=json.dumps(request).encode("utf-8"),
        capture_output=True,
        timeout=60,
        cwd=str(_REPO_ROOT),
        env=env,
    )
    assert proc.returncode in (0, 1), proc.stderr.decode("utf-8", errors="replace")
    return json.loads(proc.stdout.decode("utf-8"))


def _plugin_request(tmp_path: Path, block_type: str = "mini_write_test") -> tuple[dict, Path]:
    plugin = tmp_path / "mini_block.py"
    plugin.write_text(_MINI_PLUGIN.format(block_type=block_type), encoding="utf-8")
    target = tmp_path / "out" / "ok.txt"
    # 预建输出目录：无 allow_write 时 Low 完整级会在 mkdir 处先行拒绝（WinError 5），
    # 预建后首个被拒操作落在审计钩子可见的 open 上，断言才能命中策略文案。
    target.parent.mkdir(parents=True, exist_ok=True)
    request = {
        "kind": "plugin",
        "path": str(plugin),
        "block_type": block_type,
        "params": {"target": str(target)},
        "context": {},
        "kwargs": {},
    }
    return request, target


def test_trusted_plugin_allows_file_write(tmp_path):
    request, target = _plugin_request(tmp_path)
    response = _run_worker({**request, "allow_write": True})
    assert response["ok"] is True, response.get("error")
    assert response["result"] == {"ok": True, "written": True}
    assert target.read_text(encoding="utf-8") == "done"


def test_plugin_without_allow_write_still_blocked(tmp_path):
    request, _ = _plugin_request(tmp_path)
    response = _run_worker(request)
    assert response["ok"] is False
    assert "禁止文件写入" in response["error"]


def test_allow_write_ignored_for_script_kind(tmp_path):
    # script 请求即使携带 allow_write 也不放行：脚本沙箱本就不允许 pathlib/open
    script_request = {
        "kind": "script",
        "code": "from pathlib import Path\nPath(r'%s').write_text('x', encoding='utf-8')"
        % (tmp_path / "out" / "no.txt"),
        "context": {},
        "inputs": {},
        "allow_write": True,
    }
    response = _run_worker(script_request)
    assert response["ok"] is True  # worker 本身执行成功，业务结果在 result 里
    result = response["result"]
    assert result["ok"] is False
    assert "不允许导入模块" in result["error"]
    assert not (tmp_path / "out" / "no.txt").exists()


def test_worker_payload_utf8_on_ansi_codepage(tmp_path):
    """CI/手动启动可能落在 ANSI 代码页：无 PYTHONIOENCODING 时中文错误仍须完整输出。

    强制 cp1252 在本机也能复现编码失败模式（中文不可编码 → 修前 stdout 全空）。
    """
    request, _ = _plugin_request(tmp_path)
    env = {"PYTHONIOENCODING": "cp1252", "PYTHONUTF8": ""}
    response = _run_worker(request, extra_env=env)
    assert response["ok"] is False
    assert "禁止文件写入" in response["error"]


def test_network_blocked_even_with_allow_write(tmp_path):
    request, _ = _plugin_request(tmp_path, block_type="mini_socket_test")
    request["params"] = {}
    plugin = Path(request["path"])
    plugin.write_text(
        "SCHEMA = {'type': 'mini_socket_test', 'label': 'mini', 'category': '自定义'}\n"
        "import socket\n\n\n"
        "def handler(params, context, **kwargs):\n"
        "    socket.getaddrinfo('localhost', 80)\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )
    response = _run_worker({**request, "allow_write": True})
    assert response["ok"] is False
    assert "禁止网络访问" in response["error"]


def test_registry_user_handler_passes_allow_write(tmp_path):
    """生产注册路径：_make_isolated_user_handler 构造的 handler 默认放行写入。"""
    from backend.core.registry import _make_isolated_user_handler

    request, target = _plugin_request(tmp_path, block_type="mini_registry_test")
    handler = _make_isolated_user_handler(Path(request["path"]), "mini_registry_test")
    result = handler({"target": str(target)}, {})
    assert result["ok"] is True, result.get("error")
    assert target.read_text(encoding="utf-8") == "done"


@pytest.mark.parametrize("kind", ["plugin", "script"])
def test_subprocess_blocked_for_all_kinds(tmp_path, kind):
    request, _ = _plugin_request(tmp_path, block_type="mini_spawn_test")
    if kind == "plugin":
        Path(request["path"]).write_text(
            "SCHEMA = {'type': 'mini_spawn_test', 'label': 'mini', 'category': '自定义'}\n"
            "import subprocess\n\n\n"
            "def handler(params, context, **kwargs):\n"
            "    subprocess.Popen(['cmd', '/c', 'echo hi'])\n"
            "    return {'ok': True}\n",
            encoding="utf-8",
        )
        request["params"] = {}
        expected_marker = "禁止启动子进程"
    else:
        request = {
            "kind": "script",
            "code": (
                "import subprocess\n"
                "subprocess.Popen(['cmd', '/c', 'echo hi'])\n"
            ),
            "context": {},
            "inputs": {},
        }
        # 脚本沙箱的白名单先于审计钩子拦截 import subprocess
        expected_marker = "不允许导入模块"
    response = _run_worker({**request, "allow_write": True})
    if kind == "script":
        # 脚本沙箱自行捕获异常，业务结果嵌在 result 里
        assert response["ok"] is True
        assert response["result"]["ok"] is False
        assert expected_marker in response["result"]["error"]
    else:
        assert response["ok"] is False
        assert expected_marker in response["error"]
