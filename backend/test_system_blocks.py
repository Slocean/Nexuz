"""系统类新积木测试：系统信息 / 路径 / 环境变量 / 进程 / 磁盘 / 压缩 / 时间戳。

侧重点：只读积木的真实行为、压缩解压往返、结束进程的安全护栏（保护名单 /
拒绝自杀 / 不存在的 PID），以及新积木在执行策略与 AI run_block 里的分级。
电源 / 音量 / 打开路径等有真实桌面副作用的动作不在此真机触发。
"""

from __future__ import annotations

import os
import string
import subprocess
import sys
import time
from pathlib import Path

import pytest

from backend.core.registry import register_all_blocks

NEW_SYSTEM_BLOCKS = [
    "system_info",
    "sys_path",
    "env_var",
    "process_list",
    "process_kill",
    "open_path",
    "disk_info",
    "zip_archive",
    "power_action",
    "volume_action",
    "timestamp",
]


@pytest.fixture(scope="module", autouse=True)
def _registry():
    register_all_blocks()


def _handler(block_type: str):
    from backend.core.registry import get_handler

    handler = get_handler(block_type)
    assert callable(handler), block_type
    return handler


# --- 注册与 Schema 约定 ------------------------------------------------------


class TestRegistration:
    def test_all_new_blocks_registered(self):
        from backend.core.registry import BLOCK_REGISTRY

        for block_type in NEW_SYSTEM_BLOCKS:
            entry = BLOCK_REGISTRY.get(block_type)
            assert entry, f"积木未注册: {block_type}"
            schema = entry["schema"]
            assert schema.get("category") == "系统类", block_type
            assert schema.get("label"), block_type
            assert isinstance(schema.get("inputs"), list), block_type
            assert isinstance(schema.get("outputs"), list), block_type

    def test_show_when_fields_have_matching_option(self):
        """show_when 依赖的选择项必须真实存在于 options，防止面板永远隐藏。"""
        from backend.core.registry import BLOCK_REGISTRY

        for block_type in NEW_SYSTEM_BLOCKS:
            schema = BLOCK_REGISTRY[block_type]["schema"]
            inputs = {inp["name"]: inp for inp in schema["inputs"]}
            for inp in schema["inputs"]:
                cond = inp.get("show_when")
                if not isinstance(cond, dict):
                    continue
                for key, expected in cond.items():
                    assert key in inputs, f"{block_type}: show_when 引用未知参数 {key}"
                    options = inputs[key].get("options") or []
                    expected_list = expected if isinstance(expected, list) else [expected]
                    for item in expected_list:
                        assert item in options, f"{block_type}: {key} 缺少选项 {item}"


# --- 只读积木 ----------------------------------------------------------------


class TestReadOnlyBlocks:
    def test_system_info_sane(self):
        result = _handler("system_info")({}, {})
        assert result["ok"], result["error"]
        assert result["os_name"]
        assert result["cpu_count"] >= 1
        assert result["mem_total_gb"] > 0
        assert 0 <= result["mem_used_percent"] <= 100
        assert isinstance(result["is_admin"], bool)

    def test_sys_path_known_folders_exist(self):
        handler = _handler("sys_path")
        for key, should_exist in (("desktop", True), ("temp", True), ("home", True)):
            result = handler({"key": key}, {})
            assert result["ok"], f"{key}: {result['error']}"
            assert result["path"]
            if should_exist:
                assert Path(result["path"]).exists(), result["path"]
        bad = handler({"key": "not_a_key"}, {})
        assert not bad["ok"] and bad["error"]

    def test_timestamp_outputs(self):
        result = _handler("timestamp")({"format": "%Y%m%d"}, {})
        assert result["ok"], result["error"]
        assert result["timestamp"] > 1_600_000_000
        assert result["timestamp_ms"] > 1_600_000_000_000
        assert len(result["formatted"]) == 8
        assert result["date"].count("-") == 2
        assert result["weekday"] in ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
        bad = _handler("timestamp")({"format": "%Q不存在的指令%"}, {})
        assert not bad["ok"] and bad["error"]

    def test_disk_info_current_path_and_all(self, tmp_path):
        handler = _handler("disk_info")
        result = handler({"mode": "path", "path": str(tmp_path)}, {})
        assert result["ok"], result["error"]
        assert result["total_gb"] > 0 and result["free_gb"] <= result["total_gb"]
        assert result["drives"] and result["count"] == 1

        result = handler({"mode": "path", "path": ""}, {})
        assert result["ok"] and result["drive"]

        result = handler({"mode": "all"}, {})
        assert result["ok"] and result["count"] >= 1
        assert all(d["total_gb"] > 0 for d in result["drives"])

        # 盘符动态选取本机不存在的（写死 Z: 会在挂了 Z 盘的机器上爬到存在的
        # 祖先目录而误判）；26 个盘符全被占用时该断言无意义，直接跳过
        absent = [L for L in string.ascii_uppercase if not Path(f"{L}:/").exists()]
        if absent:
            missing = handler({"mode": "path", "path": f"{absent[0]}:\\不存在\\nope"}, {})
            assert not missing["ok"]

    def test_env_var_get_set_list(self):
        handler = _handler("env_var")

        got = handler({"action": "get", "name": "PATH"}, {})
        assert got["ok"] and got["exists"] and got["value"]

        missing = handler({"action": "get", "name": "NX_DEFINITELY_NOT_SET_9x"}, {})
        assert missing["ok"] is True  # 读取本身成功
        assert missing["exists"] is False and missing["value"] == ""

        set_result = handler({"action": "set", "name": "NX_TEST_VAR", "value": "hello"}, {})
        assert set_result["ok"]
        assert os.environ.get("NX_TEST_VAR") == "hello"
        got = handler({"action": "get", "name": "NX_TEST_VAR"}, {})
        assert got["value"] == "hello"
        del os.environ["NX_TEST_VAR"]

        listed = handler({"action": "list", "prefix": "SYSTEMROOT"}, {})
        assert listed["ok"] and "SYSTEMROOT" in listed["keys"]

        no_name = handler({"action": "get", "name": ""}, {})
        assert not no_name["ok"]

    def test_process_list_finds_python(self):
        result = _handler("process_list")({"name_filter": "python", "limit": 50}, {})
        assert result["ok"], result["error"]
        assert result["count"] >= 1
        assert result["pids"] and result["names"]
        assert any("python" in n.lower() for n in result["names"])
        assert result["count"] <= 50
        all_rows = _handler("process_list")({"name_filter": "", "limit": 5}, {})
        assert all_rows["ok"] and len(all_rows["items"]) == 5
        assert all_rows["total"] >= 5


# --- 压缩/解压 ---------------------------------------------------------------


class TestZipArchive:
    def _make_tree(self, tmp_path: Path) -> Path:
        src = tmp_path / "src"
        (src / "nested").mkdir(parents=True)
        (src / "a.txt").write_text("alpha", encoding="utf-8")
        (src / "nested" / "b.txt").write_text("beta", encoding="utf-8")
        return src

    def test_zip_files_and_folder_roundtrip(self, tmp_path):
        handler = _handler("zip_archive")
        src = self._make_tree(tmp_path)
        out_zip = tmp_path / "out" / "pack.zip"

        result = handler(
            {
                "action": "zip",
                "sources": f"{src / 'a.txt'}\n{src / 'nested'}",
                "output": str(out_zip),
            },
            {},
        )
        assert result["ok"], result["error"]
        assert out_zip.is_file() and result["count"] == 2

        result = handler({"action": "unzip", "zip_path": str(out_zip)}, {})
        assert result["ok"], result["error"]
        dest = Path(result["output"])
        assert (dest / "a.txt").read_text(encoding="utf-8") == "alpha"
        assert (dest / "nested" / "b.txt").read_text(encoding="utf-8") == "beta"

    def test_zip_default_output_next_to_source(self, tmp_path):
        handler = _handler("zip_archive")
        src = self._make_tree(tmp_path)
        result = handler({"action": "zip", "sources": str(src), "output": ""}, {})
        assert result["ok"], result["error"]
        expected = tmp_path / "src.zip"
        assert Path(result["output"]) == expected and expected.is_file()

    def test_unzip_missing_and_nonempty_dest(self, tmp_path):
        handler = _handler("zip_archive")
        src = self._make_tree(tmp_path)
        out_zip = tmp_path / "pack.zip"
        assert handler({"action": "zip", "sources": str(src), "output": str(out_zip)}, {})["ok"]

        missing = handler({"action": "unzip", "zip_path": str(tmp_path / "nope.zip")}, {})
        assert not missing["ok"]

        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "keep.txt").write_text("x", encoding="utf-8")
        blocked = handler(
            {"action": "unzip", "zip_path": str(out_zip), "output": str(dest), "overwrite": "false"},
            {},
        )
        assert not blocked["ok"]

    def test_unzip_rejects_path_traversal(self, tmp_path):
        import zipfile

        evil = tmp_path / "evil.zip"
        with zipfile.ZipFile(evil, "w") as zf:
            info = zipfile.ZipInfo("../escape.txt")
            zf.writestr(info, "boom")
        result = _handler("zip_archive")({"action": "unzip", "zip_path": str(evil)}, {})
        assert not result["ok"] and "不安全路径" in result["error"]
        assert not (tmp_path / "escape.txt").exists()

    def test_zip_source_not_found(self, tmp_path):
        result = _handler("zip_archive")(
            {"action": "zip", "sources": str(tmp_path / "ghost.txt"), "output": ""}, {}
        )
        assert not result["ok"]


# --- 结束进程护栏 ------------------------------------------------------------


class TestProcessKill:
    def test_kill_spawned_process_by_pid(self, tmp_path):
        script = tmp_path / "sleeper.py"
        script.write_text("import time; time.sleep(120)", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1.0)
        try:
            result = _handler("process_kill")(
                {"target_mode": "pid", "pid": proc.pid, "force": "true"}, {}
            )
            assert result["ok"], result["error"]
            assert result["killed_count"] == 1 and proc.pid in result["killed_pids"]
            proc.wait(timeout=10)
            assert proc.poll() is not None
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    def test_refuses_own_pid(self):
        result = _handler("process_kill")({"target_mode": "pid", "pid": os.getpid()}, {})
        assert not result["ok"]
        assert result["refused"] and not result["killed_pids"]

    def test_refuses_system_critical_names(self):
        for name in ("lsass.exe", "csrss.exe", "System"):
            result = _handler("process_kill")({"target_mode": "name", "name": name}, {})
            assert not result["ok"], name
            assert not result["killed_pids"], name

    def test_missing_target_errors(self):
        by_pid = _handler("process_kill")({"target_mode": "pid", "pid": 0}, {})
        assert not by_pid["ok"]
        by_name_empty = _handler("process_kill")({"target_mode": "name", "name": "  "}, {})
        assert not by_name_empty["ok"]
        not_found = _handler("process_kill")({"target_mode": "pid", "pid": 999999}, {})
        assert not not_found["ok"] and not not_found["killed_pids"]

    def test_name_matching_is_exact_not_prefix(self, monkeypatch):
        """system 不得外溢命中 SystemSettings.exe；notepad 须命中 notepad.exe。"""
        from backend.blocks import _os_ops

        class _FakeProc:
            def __init__(self, pid, name):
                self._pid, self._name = pid, name
                self.info = {"pid": pid, "name": name}
                self.terminated = False

            @property
            def pid(self):
                return self._pid

            def name(self):
                return self._name

            def terminate(self):
                self.terminated = True

            def wait(self, timeout=None):
                pass

        class _FakePsutil:
            class NoSuchProcess(Exception):
                pass

            class TimeoutExpired(Exception):
                pass

            class AccessDenied(Exception):
                pass

            def __init__(self, procs):
                self.procs = procs

            def process_iter(self, attrs=None):
                yield from self.procs

            def Process(self, pid):
                for proc in self.procs:
                    if proc.pid == pid:
                        return proc
                raise self.NoSuchProcess()

        procs = [
            _FakeProc(100, "System"),
            _FakeProc(101, "SystemSettings.exe"),
            _FakeProc(102, "notepad.exe"),
        ]
        fake = _FakePsutil(procs)
        monkeypatch.setattr(_os_ops, "_psutil", lambda: fake)

        result = _os_ops.kill_processes(name="system")
        assert result["killed"] == [] and result["refused"]
        assert not procs[0].terminated
        assert not procs[1].terminated  # 前缀相近但未被波及

        result = _os_ops.kill_processes(name="notepad")
        assert result["killed"] == [102] and not result["refused"]
        assert procs[2].terminated

        result = _os_ops.kill_processes(name="SystemSettings")
        assert result["killed"] == [101]


# --- 执行策略 / AI 分级 -------------------------------------------------------


class TestPolicyTiers:
    def test_elevated_types_included(self):
        from backend.core.execution_policy import ELEVATED_TYPES

        for block_type in ("process_kill", "power_action", "zip_archive", "open_path"):
            assert block_type in ELEVATED_TYPES, block_type

    def test_safe_mode_blocks_elevated_new_blocks(self):
        from backend.core.execution_policy import scan_flow_violations

        flow = {
            "entry": "s",
            "execution_policy": {"mode": "safe"},
            "nodes": {
                "s": {"type": "process_kill", "params": {"name": "x"}},
                "t": {"type": "timestamp", "params": {}},
            },
        }
        violations = scan_flow_violations(flow)
        assert [v["node_id"] for v in violations] == ["s"]
        assert violations[0]["block_type"] == "process_kill"

    def test_standard_mode_allows_elevated_but_not_critical(self):
        from backend.core.execution_policy import scan_flow_violations

        flow = {
            "entry": "s",
            "execution_policy": {"mode": "standard"},
            "nodes": {
                "s": {"type": "process_kill", "params": {"name": "x"}},
                "c": {"type": "run_command", "params": {"command": "x"}},
            },
        }
        violations = scan_flow_violations(flow)
        assert [v["node_id"] for v in violations] == ["c"]

    def test_ai_run_block_tiers(self):
        from backend.core.ai.run_block import classify_run_block

        for block_type in ("system_info", "sys_path", "disk_info", "process_list", "timestamp"):
            assert classify_run_block(block_type) == "safe", block_type
        for block_type in ("env_var", "open_path", "volume_action", "process_kill", "zip_archive"):
            assert classify_run_block(block_type) == "action", block_type
        # 关机/重启影响整机，不允许 AI 实时执行
        assert classify_run_block("power_action") is None


# --- AI run_block 实跑（safe 级） --------------------------------------------


class TestAiRunBlockSafe:
    def test_timestamp_via_run_block_once(self):
        from backend.core.ai.run_block import run_block_once

        result = run_block_once(
            {"type": "timestamp", "params": {"format": "%Y"}},
            run_ctx={"context": {}, "counter": 0},
            allow_run_block=True,
            allow_dangerous=False,
        )
        assert result["ok"] and result["tier"] == "safe"
        year = result["result"]["formatted"]
        assert len(str(year)) == 4

    def test_action_tier_requires_dangerous_flag(self):
        from backend.core.ai.run_block import run_block_once

        result = run_block_once(
            {"type": "volume_action", "params": {"action": "down", "steps": 1}},
            run_ctx={"context": {}, "counter": 0},
            allow_run_block=True,
            allow_dangerous=False,
        )
        assert not result["ok"] and "危险模式" in result["error"]
