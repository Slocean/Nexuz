from __future__ import annotations

import io
import json
import zipfile

import pytest

from backend.core.data_pack import (
    build_data_pack_bytes,
    inspect_data_pack,
    restore_data_pack,
)


def test_export_filters_runtime_data_and_redacts_keys(tmp_path):
    data = tmp_path / "data"
    (data / "flows").mkdir(parents=True)
    (data / "flows" / "demo.flow.json").write_text("{}", encoding="utf-8")
    (data / "logs").mkdir()
    (data / "logs" / "runtime.jsonl").write_text("secret log", encoding="utf-8")
    raw = build_data_pack_bytes(
        data,
        {
            "ai": {
                "api_key": "dpapi:v1:secret",
                "options": {"openai": {"api_key": "dpapi:v1:slot"}},
            },
            "notice_read_id": "notice",
        },
    )

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = set(archive.namelist())
        config = json.loads(archive.read("config.redacted.json"))
    assert "data/flows/demo.flow.json" in names
    assert not any(name.startswith("data/logs/") for name in names)
    assert "api_key" not in config["ai"]
    assert "api_key" not in config["ai"]["options"]["openai"]
    assert "notice_read_id" not in config


def test_inspection_rejects_zip_slip(tmp_path):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({
            "format": "nexuz-data-pack",
            "format_version": 1,
            "entries": [],
        }))
        archive.writestr("../evil.txt", "bad")
    with pytest.raises(ValueError, match="非法路径"):
        inspect_data_pack(path)


def test_restore_creates_backup_and_keeps_local_api_key(tmp_path):
    source = tmp_path / "source"
    (source / "flows").mkdir(parents=True)
    (source / "flows" / "new.flow.json").write_text('{"name":"new"}', encoding="utf-8")
    package = tmp_path / "backup.nexuz.zip"
    package.write_bytes(
        build_data_pack_bytes(
            source,
            {"ui": {"theme": "dark"}, "ai": {"model": "new-model"}},
        )
    )

    target = tmp_path / "target"
    (target / "flows").mkdir(parents=True)
    (target / "flows" / "old.flow.json").write_text('{"name":"old"}', encoding="utf-8")
    merged, backup = restore_data_pack(
        package,
        target,
        {"ai": {"api_key": "dpapi:v1:local", "model": "old-model"}},
    )

    assert (target / "flows" / "new.flow.json").is_file()
    assert not (target / "flows" / "old.flow.json").exists()
    assert (backup / "data" / "flows" / "old.flow.json").is_file()
    assert merged["ai"]["api_key"] == "dpapi:v1:local"
    assert merged["ai"]["model"] == "new-model"
