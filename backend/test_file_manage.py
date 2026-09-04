"""文件整理积木测试：移动 / 复制 / 重命名 / 新建文件夹 / 列出内容。

侧重点：各动作的真实文件系统行为（覆盖护栏、多来源、路径安全检查、
列目录过滤与截断），以及该积木在执行策略与 AI run_block 里的分级闸门。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.blocks import file_manage
from backend.core.registry import register_all_blocks


@pytest.fixture(scope="module", autouse=True)
def _registry():
    register_all_blocks()


def _handler():
    from backend.core.registry import get_handler

    handler = get_handler("file_manage")
    assert callable(handler)
    return lambda params: handler(params, {})


def _mk(path: Path, text: str = "x") -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# --- 注册与 Schema 约定 ------------------------------------------------------


class TestRegistration:
    def test_registered_with_schema(self):
        from backend.core.registry import BLOCK_REGISTRY

        entry = BLOCK_REGISTRY.get("file_manage")
        assert entry, "积木未注册: file_manage"
        schema = entry["schema"]
        assert schema.get("category") == "系统类"
        assert schema.get("label")
        assert isinstance(schema.get("inputs"), list)
        assert isinstance(schema.get("outputs"), list)

    def test_show_when_fields_have_matching_option(self):
        from backend.core.registry import BLOCK_REGISTRY

        schema = BLOCK_REGISTRY["file_manage"]["schema"]
        inputs = {inp["name"]: inp for inp in schema["inputs"]}
        for inp in schema["inputs"]:
            cond = inp.get("show_when")
            if not isinstance(cond, dict):
                continue
            for key, expected in cond.items():
                assert key in inputs, f"show_when 引用未知参数 {key}"
                options = inputs[key].get("options") or []
                expected_list = expected if isinstance(expected, list) else [expected]
                for item in expected_list:
                    assert item in options, f"{key} 缺少选项 {item}"


# --- 移动 --------------------------------------------------------------------


class TestMove:
    def test_move_single_to_new_path_creates_parents(self, tmp_path):
        src = _mk(tmp_path / "a.txt", "hi")
        dst = tmp_path / "nested" / "sub" / "b.txt"

        res = _handler()({"action": "move", "sources": str(src), "output": str(dst)})

        assert res["ok"], res["error"]
        assert not src.exists() and dst.exists() and dst.read_text(encoding="utf-8") == "hi"
        assert res["count"] == 1
        assert res["items"][0]["dst"] == str(dst)

    def test_move_single_into_existing_dir(self, tmp_path):
        src = _mk(tmp_path / "a.txt")
        destdir = tmp_path / "d"
        destdir.mkdir()

        res = _handler()({"action": "move", "sources": str(src), "output": str(destdir)})

        assert res["ok"], res["error"]
        assert (destdir / "a.txt").exists() and not src.exists()

    def test_move_multi_sources_into_created_dir(self, tmp_path):
        f1 = _mk(tmp_path / "one.txt")
        f2 = _mk(tmp_path / "two.txt")
        out = tmp_path / "out"

        res = _handler()({"action": "move", "sources": f"{f1}\n{f2}", "output": str(out)})

        assert res["ok"], res["error"]
        assert res["count"] == 2
        assert (out / "one.txt").exists() and (out / "two.txt").exists()
        assert not f1.exists() and not f2.exists()

    def test_move_accepts_list_sources(self, tmp_path):
        f1 = _mk(tmp_path / "one.txt")
        f2 = _mk(tmp_path / "two.txt")
        out = tmp_path / "out"

        res = _handler()({"action": "move", "sources": [str(f1), str(f2)], "output": str(out)})

        assert res["ok"], res["error"]
        assert res["count"] == 2

    def test_move_collision_refused_and_source_untouched(self, tmp_path):
        src = _mk(tmp_path / "a.txt", "new")
        out = tmp_path / "out"
        out.mkdir()
        _mk(out / "a.txt", "old")

        res = _handler()({"action": "move", "sources": str(src), "output": str(out)})

        assert not res["ok"] and "目标已存在" in res["error"]
        assert src.read_text(encoding="utf-8") == "new"
        assert (out / "a.txt").read_text(encoding="utf-8") == "old"

    def test_move_overwrite_replaces_file(self, tmp_path):
        src = _mk(tmp_path / "a.txt", "new")
        out = tmp_path / "out"
        out.mkdir()
        _mk(out / "a.txt", "old")

        res = _handler()(
            {"action": "move", "sources": str(src), "output": str(out), "overwrite": "true"}
        )

        assert res["ok"], res["error"]
        assert (out / "a.txt").read_text(encoding="utf-8") == "new"
        assert not src.exists()

    def test_move_multi_onto_file_target_refused(self, tmp_path):
        f1 = _mk(tmp_path / "one.txt")
        f2 = _mk(tmp_path / "two.txt")

        res = _handler()({"action": "move", "sources": f"{f1}\n{f2}", "output": str(f1)})

        assert not res["ok"] and f1.exists() and f2.exists()

    def test_move_dir_into_itself_refused(self, tmp_path):
        d = tmp_path / "d"
        sub = d / "sub"
        sub.mkdir(parents=True)

        res = _handler()({"action": "move", "sources": str(d), "output": str(sub)})

        assert not res["ok"] and "来源内部" in res["error"]
        assert d.exists()

    def test_move_into_own_dir_refused(self, tmp_path):
        src = _mk(tmp_path / "a.txt")

        res = _handler()({"action": "move", "sources": str(src), "output": str(tmp_path)})

        assert not res["ok"]

    def test_move_missing_source_refused(self, tmp_path):
        out = tmp_path / "out"
        res = _handler()(
            {"action": "move", "sources": str(tmp_path / "nope.txt"), "output": str(out)}
        )

        assert not res["ok"] and "来源不存在" in res["error"]

    def test_move_empty_sources_refused(self, tmp_path):
        res = _handler()({"action": "move", "sources": "", "output": str(tmp_path / "o")})

        assert not res["ok"] and "来源不能为空" in res["error"]


# --- 复制 --------------------------------------------------------------------


class TestCopy:
    def test_copy_file_keeps_source(self, tmp_path):
        src = _mk(tmp_path / "a.txt", "hi")
        dst = tmp_path / "b.txt"

        res = _handler()({"action": "copy", "sources": str(src), "output": str(dst)})

        assert res["ok"], res["error"]
        assert src.exists() and dst.read_text(encoding="utf-8") == "hi"

    def test_copy_multi_into_dir(self, tmp_path):
        f1 = _mk(tmp_path / "one.txt")
        f2 = _mk(tmp_path / "two.txt")
        out = tmp_path / "out"

        res = _handler()({"action": "copy", "sources": f"{f1}\n{f2}", "output": str(out)})

        assert res["ok"], res["error"]
        assert (out / "one.txt").exists() and f1.exists()

    def test_copy_dir(self, tmp_path):
        src = tmp_path / "src"
        (src / "sub").mkdir(parents=True)
        _mk(src / "sub" / "f.txt")
        dst = tmp_path / "dst"

        res = _handler()({"action": "copy", "sources": str(src), "output": str(dst)})

        assert res["ok"], res["error"]
        assert (dst / "sub" / "f.txt").exists() and (src / "sub" / "f.txt").exists()

    def test_copy_dir_collision_then_merge(self, tmp_path):
        src = tmp_path / "content"
        src.mkdir()
        _mk(src / "f.txt", "new")
        out = tmp_path / "out"
        out.mkdir()
        (out / "content").mkdir()
        _mk(out / "content" / "old.txt", "old")

        first = _handler()({"action": "copy", "sources": str(src), "output": str(out)})
        assert not first["ok"] and "目标已存在" in first["error"]

        merged = _handler()(
            {"action": "copy", "sources": str(src), "output": str(out), "overwrite": "true"}
        )
        assert merged["ok"], merged["error"]
        assert (out / "content" / "f.txt").read_text(encoding="utf-8") == "new"
        assert (out / "content" / "old.txt").read_text(encoding="utf-8") == "old"


# --- 重命名 ------------------------------------------------------------------


class TestRename:
    def test_rename_file(self, tmp_path):
        src = _mk(tmp_path / "a.txt")

        res = _handler()({"action": "rename", "path": str(src), "name": "b.txt"})

        assert res["ok"], res["error"]
        assert not src.exists() and (tmp_path / "b.txt").exists()

    def test_rename_dir(self, tmp_path):
        d = tmp_path / "d"
        d.mkdir()

        res = _handler()({"action": "rename", "path": str(d), "name": "e"})

        assert res["ok"], res["error"]
        assert (tmp_path / "e").is_dir()

    def test_rename_rejects_path_separators(self, tmp_path):
        src = _mk(tmp_path / "a.txt")

        for bad in ("a\\b", "a/b", "C:x", ".."):
            res = _handler()({"action": "rename", "path": str(src), "name": bad})
            assert not res["ok"], bad
        assert src.exists()

    def test_rename_existing_target_refused(self, tmp_path):
        src = _mk(tmp_path / "a.txt", "src")
        other = _mk(tmp_path / "b.txt", "other")

        res = _handler()({"action": "rename", "path": str(src), "name": "b.txt"})

        assert not res["ok"] and "目标名已存在" in res["error"]
        assert src.exists() and other.read_text(encoding="utf-8") == "other"

    def test_rename_missing_path_refused(self, tmp_path):
        res = _handler()({"action": "rename", "path": str(tmp_path / "nope"), "name": "x"})

        assert not res["ok"] and "不存在" in res["error"]


# --- 新建文件夹 --------------------------------------------------------------


class TestMkdir:
    def test_mkdir_nested(self, tmp_path):
        target = tmp_path / "a" / "b" / "c"

        res = _handler()({"action": "mkdir", "path": str(target)})

        assert res["ok"], res["error"]
        assert target.is_dir() and res["count"] == 1

    def test_mkdir_existing_dir_idempotent(self, tmp_path):
        d = tmp_path / "d"
        d.mkdir()

        res = _handler()({"action": "mkdir", "path": str(d)})

        assert res["ok"] and res["count"] == 0

    def test_mkdir_existing_file_refused(self, tmp_path):
        f = _mk(tmp_path / "a.txt")

        res = _handler()({"action": "mkdir", "path": str(f)})

        assert not res["ok"] and f.is_file()


# --- 列出内容 ----------------------------------------------------------------


class TestList:
    def test_list_returns_sorted_entries(self, tmp_path):
        _mk(tmp_path / "b.txt")
        _mk(tmp_path / "a.txt")
        (tmp_path / "sub").mkdir()

        res = _handler()({"action": "list", "path": str(tmp_path)})

        assert res["ok"], res["error"]
        assert res["count"] == 3
        assert [e["name"] for e in res["items"]] == ["a.txt", "b.txt", "sub"]
        file_entry = res["items"][0]
        assert file_entry["type"] == "file" and file_entry["size"] == 1
        assert file_entry["mtime"]
        assert res["items"][2]["type"] == "dir" and "size" not in res["items"][2]
        assert res["output"] == str(tmp_path)

    def test_list_pattern_and_kind_filters(self, tmp_path):
        _mk(tmp_path / "a.jpg")
        _mk(tmp_path / "b.txt")
        (tmp_path / "c.jpg").mkdir()

        jpg = _handler()({"action": "list", "path": str(tmp_path), "pattern": "*.jpg"})
        assert [e["name"] for e in jpg["items"]] == ["a.jpg", "c.jpg"]

        files_only = _handler()({"action": "list", "path": str(tmp_path), "kind": "file"})
        assert [e["name"] for e in files_only["items"]] == ["a.jpg", "b.txt"]

        dirs_only = _handler()({"action": "list", "path": str(tmp_path), "kind": "dir"})
        assert [e["name"] for e in dirs_only["items"]] == ["c.jpg"]

    def test_list_truncated_at_cap(self, tmp_path, monkeypatch):
        for i in range(5):
            _mk(tmp_path / f"f{i}.txt")
        monkeypatch.setattr(file_manage, "MAX_LIST_ENTRIES", 3)

        res = _handler()({"action": "list", "path": str(tmp_path)})

        assert res["ok"]
        assert res["count"] == 3 and res["truncated"] is True

    def test_list_non_dir_refused(self, tmp_path):
        f = _mk(tmp_path / "a.txt")

        res = _handler()({"action": "list", "path": str(f)})

        assert not res["ok"]

    def test_list_items_json_serializable(self, tmp_path):
        _mk(tmp_path / "a.txt")
        res = _handler()({"action": "list", "path": str(tmp_path)})

        assert json.loads(json.dumps(res["items"], ensure_ascii=False))


# --- 执行策略 / AI 分级 -------------------------------------------------------


class TestPolicyTiers:
    def test_elevated_and_action_tier(self):
        from backend.core.ai.run_block import classify_run_block
        from backend.core.execution_policy import ELEVATED_TYPES

        assert "file_manage" in ELEVATED_TYPES
        assert classify_run_block("file_manage") == "action"

    def test_safe_mode_blocks_file_manage(self):
        from backend.core.execution_policy import scan_flow_violations

        flow = {
            "entry": "s",
            "execution_policy": {"mode": "safe"},
            "nodes": {
                "s": {"type": "file_manage", "params": {"action": "move"}},
                "t": {"type": "timestamp", "params": {}},
            },
        }
        violations = scan_flow_violations(flow)
        assert [v["node_id"] for v in violations] == ["s"]
        assert violations[0]["block_type"] == "file_manage"

    def test_standard_mode_allows_file_manage(self):
        from backend.core.execution_policy import scan_flow_violations

        flow = {
            "entry": "s",
            "execution_policy": {"mode": "standard"},
            "nodes": {"s": {"type": "file_manage", "params": {"action": "move"}}},
        }
        assert scan_flow_violations(flow) == []


# --- AI run_block 闸门 --------------------------------------------------------


class TestAiRunBlockGate:
    def test_requires_allow_run_block(self, tmp_path):
        from backend.core.ai.run_block import run_block_once

        res = run_block_once(
            {"type": "file_manage", "params": {"action": "mkdir", "path": str(tmp_path / "x")}},
            run_ctx={"context": {}, "counter": 0},
            allow_run_block=False,
            allow_dangerous=True,
        )
        assert not res["ok"] and "允许 AI 实时执行" in res["error"]
        assert not (tmp_path / "x").exists()

    def test_action_tier_requires_dangerous(self, tmp_path):
        from backend.core.ai.run_block import run_block_once

        res = run_block_once(
            {"type": "file_manage", "params": {"action": "mkdir", "path": str(tmp_path / "x")}},
            run_ctx={"context": {}, "counter": 0},
            allow_run_block=True,
            allow_dangerous=False,
        )
        assert not res["ok"] and "危险模式" in res["error"]
        assert not (tmp_path / "x").exists()

    def test_executes_with_both_switches(self, tmp_path):
        from backend.core.ai.run_block import run_block_once

        res = run_block_once(
            {
                "type": "file_manage",
                "params": {"action": "mkdir", "path": str(tmp_path / "made")},
            },
            run_ctx={"context": {}, "counter": 0},
            allow_run_block=True,
            allow_dangerous=True,
        )
        assert res["ok"] and res["tier"] == "action"
        assert (tmp_path / "made").is_dir()
        assert res["result"]["count"] == 1


# --- AI 工具目录可见性 --------------------------------------------------------


class TestToolCatalog:
    def test_hidden_without_dangerous_visible_with(self):
        from backend.core.ai.tool_catalog import get_block_schema, list_blocks

        assert all(b["type"] != "file_manage" for b in list_blocks(allow_dangerous=False))
        types = {b["type"] for b in list_blocks(allow_dangerous=True)}
        assert "file_manage" in types
        schema = get_block_schema("file_manage", allow_dangerous=True)
        assert schema and schema["type"] == "file_manage"
        denied = get_block_schema("file_manage", allow_dangerous=False)
        assert denied and "error" in denied and "inputs" not in denied


# ---- 路径归一化的防呆（盘符相对路径 / 控制字符）----


def test_list_rejects_drive_relative_path(tmp_path):
    """D:nexuz（丢反斜杠）曾被静默锚定到进程 cwd，造成"路径被拼接"的错觉——现明确报错。"""
    from backend.blocks._system_io import normalize_path

    p, err = normalize_path("D:nexuz")
    assert p is None and err is not None
    assert "盘符相对路径" in err and ("D:" + chr(92) + "nexuz") in err

    r = file_manage.handler({"action": "list", "path": "D:nexuz"}, {})
    assert r["ok"] is False and "盘符相对路径" in r["error"]


def test_list_rejects_control_chars_in_path():
    """JSON 转义事故（"D:\nexuz" 单反斜杠 → \n 变换行）给出可诊断的报错。"""
    from backend.blocks._system_io import normalize_path

    mangled = "D:" + chr(10) + "exuz"
    p, err = normalize_path(mangled)
    assert p is None and err is not None
    assert "控制字符" in err

    r = file_manage.handler({"action": "list", "path": mangled}, {})
    assert r["ok"] is False and "控制字符" in r["error"]


def test_list_normal_absolute_forms_still_work(tmp_path):
    """绝对路径各形态（反斜杠/正斜杠/尾分隔符/双写转义）不受影响。"""
    base = tmp_path / "nexuz"
    base.mkdir()
    (base / "a.txt").write_text("x", encoding="utf-8")
    for form in (str(base), str(base).replace("\\", "/"), str(base) + "\\", str(base).replace("\\", "\\\\")):
        r = file_manage.handler({"action": "list", "path": form}, {})
        assert r["ok"] is True, f"{form!r}: {r['error']}"
        assert r["count"] == 1 and r["items"][0]["name"] == "a.txt"
