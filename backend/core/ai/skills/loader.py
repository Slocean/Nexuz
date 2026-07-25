"""Load and apply skill.yaml packs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_SKILLS_DIR = Path(__file__).resolve().parent / "packs"
_CACHE: dict[str, dict[str, Any]] | None = None


def skills_dir() -> Path:
    return _SKILLS_DIR


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Minimal YAML subset (key: value, nested under expand:) without PyYAML dependency."""
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass
    # Fallback: JSON-in-file or trivial line parser for our packs
    out: dict[str, Any] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if ":" in s and not s.startswith("-"):
            k, v = s.split(":", 1)
            key = k.strip()
            val = v.strip().strip('"').strip("'")
            if val.lower() in ("true", "false"):
                out[key] = val.lower() == "true"
            elif val.isdigit():
                out[key] = int(val)
            else:
                out[key] = val
    return out


def _load_all() -> dict[str, dict[str, Any]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    found: dict[str, dict[str, Any]] = {}
    root = skills_dir()
    if root.is_dir():
        for path in sorted(root.glob("*/skill.yaml")):
            try:
                raw = _parse_simple_yaml(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            sid = str(raw.get("id") or path.parent.name).strip()
            if not sid:
                continue
            raw["_path"] = str(path)
            raw["enabled"] = raw.get("enabled", True) is not False
            found[sid] = raw
        for path in sorted(root.glob("*/skill.json")):
            try:
                import json

                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(raw, dict):
                continue
            sid = str(raw.get("id") or path.parent.name).strip()
            raw["_path"] = str(path)
            raw["enabled"] = raw.get("enabled", True) is not False
            found[sid] = raw
    _CACHE = found
    return found


def reload_skills() -> None:
    global _CACHE
    _CACHE = None
    _load_all()


def _config_disabled() -> set[str]:
    try:
        from backend.core.ai.config import get_ai_config

        return set(get_ai_config().disabled_skills or [])
    except Exception:
        return set()


def list_skills(*, include_disabled: bool = False) -> list[dict[str, Any]]:
    disabled = _config_disabled()
    items = []
    for sid, raw in sorted(_load_all().items()):
        pack_enabled = bool(raw.get("enabled", True))
        user_enabled = sid not in disabled
        enabled = pack_enabled and user_enabled
        if not include_disabled and not enabled:
            continue
        items.append(
            {
                "id": sid,
                "label": raw.get("label") or sid,
                "description": raw.get("description") or "",
                "triggers": raw.get("triggers") or [],
                "permission": raw.get("permission") or "safe",
                "enabled": enabled,
                "recipe": raw.get("recipe") or sid,
            }
        )
    return items


def load_skill(skill_id: str) -> dict[str, Any] | None:
    return _load_all().get((skill_id or "").strip())


def try_apply_skill(
    skill_id: str,
    draft: dict[str, Any],
    *,
    params: dict[str, Any],
    last_node_id: str | None,
    artifacts: dict[str, Any],
    tool_trace: list[dict[str, Any]],
    runtime: Any,
) -> str | None:
    """
    Apply a skill pack. Returns new last_node_id, or None if skill unknown.
    Built-in recipes in recipes.py take precedence (called before this).
    """
    skill = load_skill(skill_id)
    if skill is None or not skill.get("enabled", True):
        return None
    if skill_id in _config_disabled():
        return None
    recipe = str(skill.get("recipe") or skill_id)
    # Map pack → known recipe names already handled — if we got here, expand steps
    expand = skill.get("expand") or skill.get("steps")
    if not isinstance(expand, list):
        # Delegate by setting recipe alias
        if recipe != skill_id:
            from backend.core.ai.lc.structured import PlanStep
            from backend.core.ai.graphs import recipes as recipes_mod

            step = PlanStep(action="recipe", recipe=recipe, params=params)
            return recipes_mod._apply_step(
                draft,
                artifacts,
                step,
                runtime=runtime,
                tool_trace=tool_trace,
                last_node_id=last_node_id,
            )
        return None

    from backend.core.ai.lc.structured import PlanStep
    from backend.core.ai.graphs import recipes as recipes_mod

    cur = last_node_id
    for item in expand:
        if not isinstance(item, dict):
            continue
        merged = {**(item.get("params") or {}), **params}
        step = PlanStep(
            action=str(item.get("action") or "recipe"),
            recipe=item.get("recipe"),
            block_type=item.get("block_type"),
            match_text=item.get("match_text") or params.get("match_text"),
            params=merged,
            node_id=item.get("node_id"),
        )
        cur = recipes_mod._apply_step(
            draft,
            artifacts,
            step,
            runtime=runtime,
            tool_trace=tool_trace,
            last_node_id=cur,
        )
    return cur
