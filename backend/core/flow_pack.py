"""Pack / unpack a flow with template images for portable share."""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Iterable

ASSET_PARAM_KEYS = ("template_image", "anchor_template")
FLOW_JSON_NAME = "flow.json"
ASSETS_DIR = "assets"


def iter_asset_refs(flow: dict[str, Any]) -> Iterable[tuple[str, str, str]]:
    """Yield (node_id, param_key, path_str) for image refs on nodes."""
    nodes = flow.get("nodes") if isinstance(flow, dict) else None
    if not isinstance(nodes, dict):
        return
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        params = node.get("params") or {}
        if not isinstance(params, dict):
            continue
        for key in ASSET_PARAM_KEYS:
            raw = params.get(key)
            if isinstance(raw, str) and raw.strip():
                yield str(node_id), key, raw.strip()


def _safe_asset_name(path: Path, used: set[str]) -> str:
    base = path.name or "asset.bin"
    base = re.sub(r"[^\w.\-]+", "_", base, flags=re.UNICODE)
    if not base.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif")):
        base = f"{base}.png"
    name = base
    i = 1
    while name in used:
        stem = Path(base).stem
        suffix = Path(base).suffix or ".png"
        name = f"{stem}_{i}{suffix}"
        i += 1
    used.add(name)
    return name


def collect_assets(flow: dict[str, Any]) -> tuple[dict[str, Any], dict[str, bytes]]:
    """
    Rewrite asset paths in a deep-copied flow to ``assets/<name>``.
    Returns (rewritten_flow, {assets/name: bytes}).
    Missing files are left as original paths (not packed).
    """
    packed = json.loads(json.dumps(flow))
    files: dict[str, bytes] = {}
    used_names: set[str] = set()
    # path resolve → zip relative name (dedupe identical files)
    path_to_rel: dict[str, str] = {}

    nodes = packed.get("nodes") or {}
    for node_id, key, path_str in iter_asset_refs(packed):
        try:
            src = Path(path_str).expanduser().resolve()
        except Exception:
            continue
        if not src.is_file():
            continue
        key_path = str(src)
        if key_path not in path_to_rel:
            rel_name = _safe_asset_name(src, used_names)
            try:
                files[f"{ASSETS_DIR}/{rel_name}"] = src.read_bytes()
            except OSError:
                continue
            path_to_rel[key_path] = f"{ASSETS_DIR}/{rel_name}"
        node = nodes.get(node_id)
        if isinstance(node, dict) and isinstance(node.get("params"), dict):
            node["params"][key] = path_to_rel[key_path]

    return packed, files


def build_zip_bytes(flow: dict[str, Any]) -> bytes:
    rewritten, files = collect_assets(flow)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            FLOW_JSON_NAME,
            json.dumps(rewritten, ensure_ascii=False, indent=2),
            compress_type=zipfile.ZIP_DEFLATED,
        )
        for name, raw in files.items():
            zf.writestr(name, raw, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def flow_has_packable_assets(flow: dict[str, Any]) -> bool:
    for _nid, _key, path_str in iter_asset_refs(flow):
        try:
            if Path(path_str).expanduser().is_file():
                return True
        except Exception:
            continue
    return False


def load_flow_from_zip(
    zip_path: Path,
    *,
    templates_dir: Path,
    import_image,
) -> dict[str, Any]:
    """
    Read zip, import assets via ``import_image(bytes, preferred_name) -> {ok, path}``,
    rewrite params to absolute template paths, return flow dict.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        flow_name = None
        for candidate in (FLOW_JSON_NAME, "flow.flow.json"):
            if candidate in names:
                flow_name = candidate
                break
        if flow_name is None:
            for n in names:
                if n.lower().endswith(".flow.json") or n.lower().endswith(".json"):
                    if "/" not in n.strip("/") and "\\" not in n:
                        flow_name = n
                        break
        if not flow_name:
            raise ValueError("压缩包内缺少 flow.json")
        data = json.loads(zf.read(flow_name).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("无效的流程对象")

        # Map pack-relative path → new absolute path
        rel_map: dict[str, str] = {}
        for name in names:
            norm = name.replace("\\", "/").lstrip("./")
            if not norm.startswith(f"{ASSETS_DIR}/"):
                continue
            if norm.endswith("/"):
                continue
            preferred = Path(norm).name
            raw = zf.read(name)
            saved = import_image(raw, preferred)
            if saved.get("ok") and saved.get("path"):
                rel_map[norm] = str(saved["path"])
                # also allow bare filename match
                rel_map[preferred] = str(saved["path"])
                rel_map[f"./{norm}"] = str(saved["path"])

        nodes = data.get("nodes") or {}
        if isinstance(nodes, dict):
            for _node_id, node in nodes.items():
                if not isinstance(node, dict):
                    continue
                params = node.get("params")
                if not isinstance(params, dict):
                    continue
                for key in ASSET_PARAM_KEYS:
                    raw = params.get(key)
                    if not isinstance(raw, str) or not raw.strip():
                        continue
                    rel = raw.strip().replace("\\", "/")
                    if rel in rel_map:
                        params[key] = rel_map[rel]
                    elif rel.startswith(f"{ASSETS_DIR}/") and rel in rel_map:
                        params[key] = rel_map[rel]
                    else:
                        # Already absolute on this machine — keep if exists
                        p = Path(raw)
                        if not p.is_file():
                            # try basename under templates
                            candidate = templates_dir / Path(rel).name
                            if candidate.is_file():
                                params[key] = str(candidate)

        return data


def is_zip_path(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".zip") or name.endswith(".flow.zip")
