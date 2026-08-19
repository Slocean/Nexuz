"""Safe export and restore helpers for Nexuz user-owned data."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import shutil
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

ALLOW_PREFIXES = (
    "flows/",
    "flow_templates/",
    "templates/",
    "schedules/",
    "user_blocks/",
    "ai/conversations/",
)
MAX_MEMBER_SIZE = 100 * 1024 * 1024
MAX_TOTAL_SIZE = 2 * 1024 * 1024 * 1024


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(config)
    result.pop("notice_read_id", None)
    result.pop("migrated_from_exe", None)
    result.pop("data_dir", None)
    ai = result.get("ai")
    if isinstance(ai, dict):
        key = str(ai.pop("api_key", "") or "")
        ai["has_api_key"] = bool(key)
        options = ai.get("options")
        if isinstance(options, dict):
            for slot in options.values():
                if isinstance(slot, dict):
                    slot_key = str(slot.pop("api_key", "") or "")
                    slot["has_api_key"] = bool(slot_key)
    return result


def _iter_files(data_root: Path):
    if not data_root.is_dir():
        return
    for path in data_root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(data_root).as_posix()
        if "__pycache__" in path.parts or path.suffix.lower() == ".pyc":
            continue
        if any(rel.startswith(prefix) for prefix in ALLOW_PREFIXES):
            yield path, rel


def build_data_pack_bytes(data_root: Path, config: dict[str, Any]) -> bytes:
    entries: list[dict[str, Any]] = []
    payloads: list[tuple[str, bytes]] = []
    for path, rel in _iter_files(data_root) or ():
        data = path.read_bytes()
        if len(data) > MAX_MEMBER_SIZE:
            raise ValueError(f"文件过大，无法打包: {rel}")
        archive_name = f"data/{rel}"
        payloads.append((archive_name, data))
        entries.append(
            {
                "path": archive_name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    config_data = json.dumps(
        redact_config(config), ensure_ascii=False, indent=2
    ).encode("utf-8")
    manifest = {
        "format": "nexuz-data-pack",
        "format_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
        "config_redacted": True,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
        )
        archive.writestr("config.redacted.json", config_data)
        for name, data in payloads:
            archive.writestr(name, data)
    return buffer.getvalue()


def _validate_member_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"数据包包含非法路径: {name}")
    clean = pure.as_posix()
    if clean in {"manifest.json", "config.redacted.json"}:
        return clean
    if not clean.startswith("data/"):
        raise ValueError(f"数据包包含未授权路径: {name}")
    rel = clean[5:]
    if not any(rel.startswith(prefix) for prefix in ALLOW_PREFIXES):
        raise ValueError(f"数据包包含未授权数据: {name}")
    return clean


def inspect_data_pack(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as archive:
        infos = archive.infolist()
        total_size = sum(info.file_size for info in infos)
        if total_size > MAX_TOTAL_SIZE:
            raise ValueError("数据包解压后体积超过限制")
        names = {_validate_member_name(info.filename) for info in infos}
        if "manifest.json" not in names:
            raise ValueError("数据包缺少 manifest.json")
        manifest = json.loads(archive.read("manifest.json"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("format") != "nexuz-data-pack"
            or manifest.get("format_version") != 1
        ):
            raise ValueError("不支持的数据包格式")
        entries = manifest.get("entries")
        if not isinstance(entries, list):
            raise ValueError("数据包清单无效")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("数据包清单条目无效")
            member = _validate_member_name(str(entry.get("path") or ""))
            data = archive.read(member)
            if len(data) != int(entry.get("size") or -1):
                raise ValueError(f"数据包文件大小校验失败: {member}")
            if hashlib.sha256(data).hexdigest() != str(entry.get("sha256") or ""):
                raise ValueError(f"数据包文件哈希校验失败: {member}")
        config = {}
        if "config.redacted.json" in names:
            config = json.loads(archive.read("config.redacted.json"))
            if not isinstance(config, dict):
                config = {}
        return {
            "manifest": manifest,
            "config": config,
            "file_count": len(entries),
            "total_size": sum(int(item.get("size") or 0) for item in entries),
        }


def restore_data_pack(
    path: Path,
    data_root: Path,
    current_config: dict[str, Any],
) -> tuple[dict[str, Any], Path]:
    inspected = inspect_data_pack(path)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = data_root.parent / f".nexuz-backup-{stamp}"
    if data_root.is_dir():
        shutil.copytree(data_root, backup / "data")
    with tempfile.TemporaryDirectory(prefix="nexuz-restore-") as temp:
        staging = Path(temp)
        with zipfile.ZipFile(path, "r") as archive:
            for info in archive.infolist():
                name = _validate_member_name(info.filename)
                if not name.startswith("data/") or info.is_dir():
                    continue
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))
        staged_data = staging / "data"
        try:
            for prefix in ALLOW_PREFIXES:
                relative = Path(*PurePosixPath(prefix.rstrip("/")).parts)
                source = staged_data / relative
                if not source.exists():
                    continue
                destination = data_root / relative
                if destination.exists():
                    shutil.rmtree(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, destination)
        except Exception:
            if backup.is_dir():
                if data_root.exists():
                    shutil.rmtree(data_root)
                shutil.copytree(backup / "data", data_root)
            raise
    merged = copy.deepcopy(current_config)
    imported = inspected.get("config")
    if isinstance(imported, dict):
        imported.pop("data_dir", None)
        imported_ai = imported.pop("ai", None)
        merged.update(imported)
        if isinstance(imported_ai, dict):
            local_ai = merged.get("ai") if isinstance(merged.get("ai"), dict) else {}
            imported_ai.pop("api_key", None)
            imported_ai.pop("has_api_key", None)
            imported_options = imported_ai.get("options")
            local_options = local_ai.get("options")
            if isinstance(imported_options, dict) and isinstance(local_options, dict):
                for preset, slot in imported_options.items():
                    if isinstance(slot, dict) and isinstance(local_options.get(preset), dict):
                        slot.pop("api_key", None)
                        slot.pop("has_api_key", None)
                        imported_options[preset] = {**local_options[preset], **slot}
            merged["ai"] = {**local_ai, **imported_ai}
    return merged, backup
