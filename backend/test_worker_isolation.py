"""Regression checks for trusted-code process isolation."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.registry import (
    _read_user_block_schema,
    is_user_block_trusted,
    revoke_user_block,
    trust_user_block,
)
from backend.core.worker_client import run_isolated, terminate_all_workers
from backend.blocks.python_script import handler as python_script_handler


def test_script_runs_out_of_process() -> None:
    response = run_isolated(
        {
            "kind": "script",
            "code": 'out["result"] = inputs["value"] * 2',
            "inputs": {"value": 21},
            "context": {},
        },
        timeout_seconds=3,
    )
    assert response["ok"] is True, response
    assert response["result"]["result"] == 42


def test_python_script_block_uses_worker() -> None:
    result = python_script_handler(
        {
            "code": 'out["result"] = inputs["value"] + 1',
            "inputs": {"value": 4},
            "timeout_seconds": 3,
        },
        {},
    )
    assert result["ok"] is True
    assert result["result"] == 5


def test_large_worker_output_does_not_deadlock_pipe() -> None:
    response = run_isolated(
        {
            "kind": "script",
            "code": 'print("x" * 200000)',
            "inputs": {},
            "context": {},
        },
        timeout_seconds=3,
    )
    assert response["ok"] is True, response
    assert len(response["result"]["printed"]) >= 200000


def test_infinite_script_is_terminated() -> None:
    started = time.monotonic()
    response = run_isolated(
        {"kind": "script", "code": "while True:\n    pass", "inputs": {}, "context": {}},
        timeout_seconds=0.3,
    )
    assert response["ok"] is False
    assert "超时" in response["error"]
    assert time.monotonic() - started < 5


def test_stop_request_terminates_worker() -> None:
    started = time.monotonic()
    try:
        run_isolated(
            {"kind": "script", "code": "while True:\n    pass", "inputs": {}, "context": {}},
            timeout_seconds=10,
            should_stop=lambda: time.monotonic() - started > 0.2,
        )
    except InterruptedError:
        pass
    else:
        raise AssertionError("stop request did not interrupt worker")
    assert time.monotonic() - started < 5


def test_global_force_reset_terminates_worker() -> None:
    result: dict = {}

    def invoke() -> None:
        result.update(
            run_isolated(
                {
                    "kind": "script",
                    "code": "while True:\n    pass",
                    "inputs": {},
                    "context": {},
                },
                timeout_seconds=10,
            )
        )

    thread = threading.Thread(target=invoke)
    thread.start()
    time.sleep(0.25)
    assert terminate_all_workers() >= 1
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert result.get("ok") is False


def test_plugin_schema_scan_does_not_execute_module() -> None:
    with tempfile.TemporaryDirectory() as td:
        folder = Path(td)
        marker = folder / "executed.txt"
        plugin = folder / "sample.py"
        plugin.write_text(
            "\n".join(
                [
                    "import os",
                    f"open({str(marker)!r}, 'w').write('top-level')",
                    "SCHEMA = {'type': 'sample', 'label': 'Sample', 'inputs': [], 'outputs': []}",
                    "def handler(params, context, **kwargs):",
                    "    return {'ok': True, 'pid': os.getpid()}",
                ]
            ),
            encoding="utf-8",
        )
        schema = _read_user_block_schema(plugin)
        assert schema["type"] == "sample"
        assert not marker.exists()

        response = run_isolated(
            {
                "kind": "plugin",
                "path": str(plugin),
                "block_type": "sample",
                "params": {},
                "context": {},
                "kwargs": {},
            },
            timeout_seconds=3,
        )
        assert response["ok"] is False
        assert not marker.exists()

        clean_plugin = folder / "clean.py"
        clean_plugin.write_text(
            "\n".join(
                [
                    "import os",
                    "SCHEMA = {'type': 'clean', 'label': 'Clean', 'inputs': [], 'outputs': []}",
                    "def handler(params, context, **kwargs):",
                    "    return {'ok': True, 'pid': os.getpid()}",
                ]
            ),
            encoding="utf-8",
        )
        clean_response = run_isolated(
            {
                "kind": "plugin",
                "path": str(clean_plugin),
                "block_type": "clean",
                "params": {},
                "context": {},
                "kwargs": {},
            },
            timeout_seconds=3,
        )
        assert clean_response["ok"] is True, clean_response
        assert clean_response["result"]["pid"] != os.getpid()

        network_plugin = folder / "network.py"
        network_plugin.write_text(
            "\n".join(
                [
                    "import socket",
                    "SCHEMA = {'type': 'network', 'label': 'Network', 'inputs': [], 'outputs': []}",
                    "def handler(params, context, **kwargs):",
                    "    socket.socket()",
                    "    return {'ok': True}",
                ]
            ),
            encoding="utf-8",
        )
        blocked = run_isolated(
            {
                "kind": "plugin",
                "path": str(network_plugin),
                "block_type": "network",
                "params": {},
                "context": {},
                "kwargs": {},
            },
            timeout_seconds=3,
        )
        assert blocked["ok"] is False
        assert "网络" in blocked["error"] or "PermissionError" in blocked["error"]


def test_plugin_trust_is_bound_to_file_hash() -> None:
    with tempfile.TemporaryDirectory() as td:
        plugin = Path(td) / "trusted.py"
        plugin.write_text("SCHEMA = {'type': 'trusted'}\n", encoding="utf-8")
        config: dict = {}

        def save(updated):
            config.clear()
            config.update(updated)

        with (
            patch("backend.paths.load_app_config", side_effect=lambda: dict(config)),
            patch("backend.paths.save_app_config", side_effect=save),
        ):
            trust_user_block(plugin)
            assert is_user_block_trusted(plugin)
            plugin.write_text("SCHEMA = {'type': 'changed'}\n", encoding="utf-8")
            assert not is_user_block_trusted(plugin)
            revoke_user_block(plugin)
            assert not is_user_block_trusted(plugin)


if __name__ == "__main__":
    test_script_runs_out_of_process()
    test_python_script_block_uses_worker()
    test_large_worker_output_does_not_deadlock_pipe()
    test_infinite_script_is_terminated()
    test_stop_request_terminates_worker()
    test_global_force_reset_terminates_worker()
    test_plugin_schema_scan_does_not_execute_module()
    test_plugin_trust_is_bound_to_file_hash()
    print("WORKER ISOLATION OK")
