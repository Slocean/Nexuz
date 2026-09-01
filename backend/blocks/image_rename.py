"""图片批量重命名：按自定义命名规则批量重命名图片，支持识别内容命名。

命名规则为 str.format 模板：{name} 原文件名、{n} 序号（补零位数可配，
也可手写 {n:03d}）、{width}/{height} 宽高、{date} 日期、{parent} 所在
文件夹名，以及识别占位符 {text}（OCR 文字）与 {ai}（AI 视觉命名）。
默认原地重命名，走两段式（先改临时名再改最终名）避免批次内互相覆盖；
填写输出目录则改为复制重命名，原文件保留。
"""

from __future__ import annotations

import base64
import io
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from string import Formatter
from typing import Any

import httpx

from backend.core.ai.config import get_ai_config

SCHEMA = {
    "type": "image_rename",
    "label": "图片批量重命名",
    "category": "识别类",
    # 代码级完成日志模板：流程结束时自动拼进「流程执行完成」日志；
    # 节点上手动填写的完成日志可覆盖此模板。{{字段}} 引用本节点输出。
    "done_log": "已重命名{{count}}张图片，输出目录：{{output_dir}}",
    "inputs": [
        {
            "name": "image_path",
            "type": "string",
            "label": "图片路径/文件夹",
            "default": "",
            "placeholder": "图片文件，或整个文件夹（批量）",
            "ui": "file_or_dir",
            "accept": "*.png;*.webp;*.bmp;*.jpg;*.jpeg;*.gif",
            "bindable": True,
        },
        {
            "name": "output_dir",
            "type": "string",
            "label": "输出目录",
            "default": "",
            "placeholder": "留空=原地重命名；填写=复制重命名到该目录，原文件保留",
            "ui": "file_or_dir",
        },
        {
            "name": "name_template",
            "type": "string",
            "label": "命名规则",
            "default": "",
            "placeholder": "如 game_{n} 或 {name}_{text}；可用 {name} 原名 / {n} 序号 / {width} {height} 宽高 / {date} 日期 / {parent} 文件夹名 / {text} 识别文本 / {ai} AI 命名",
            "bindable": True,
        },
        {
            "name": "recognize_mode",
            "type": "select",
            "label": "内容识别",
            "options": ["none", "ocr", "ai"],
            "default": "none",
            "option_labels": {
                "none": "关闭",
                "ocr": "OCR 文字识别",
                "ai": "AI 内容识别",
            },
            "placeholder": "识别结果填入 {text} / {ai} 占位符；AI 需在 设置 → Nexuz AI 配置支持图像的聊天模型",
        },
        {
            "name": "ocr_line",
            "type": "select",
            "label": "识别文本取值",
            "options": ["first", "longest", "join"],
            "default": "first",
            "option_labels": {
                "first": "首行（最靠上）",
                "longest": "最长的一行",
                "join": "全部用下划线连接",
            },
            "show_when": {"recognize_mode": "ocr"},
        },
        {
            "name": "ai_prompt",
            "type": "string",
            "label": "AI 命名提示词",
            "default": "",
            "placeholder": "留空用内置提示词（简短名词命名图片内容，不超过最大长度）",
            "ui": "textarea",
            "bindable": True,
            "show_when": {"recognize_mode": "ai"},
        },
        {
            "name": "timeout_s",
            "type": "number",
            "label": "AI 超时秒数",
            "default": 60,
            "placeholder": "单张图片的 AI 命名请求超时",
            "show_when": {"recognize_mode": "ai"},
        },
        {
            "name": "text_max_len",
            "type": "number",
            "label": "识别内容最大长度",
            "default": 20,
            "placeholder": "识别文本/AI 命名作为文件名的最大字符数，0=不限",
        },
        {
            "name": "start_index",
            "type": "number",
            "label": "起始序号",
            "default": 1,
        },
        {
            "name": "index_digits",
            "type": "number",
            "label": "序号位数",
            "default": 2,
            "placeholder": "序号 {n} 的补零位数（3 → 001），0=不补零",
        },
        {
            "name": "conflict_mode",
            "type": "select",
            "label": "重名处理",
            "options": ["rename", "skip", "overwrite"],
            "default": "rename",
            "option_labels": {
                "rename": "自动加后缀",
                "skip": "跳过",
                "overwrite": "覆盖",
            },
        },
        {
            "name": "dry_run",
            "type": "select",
            "label": "试运行",
            "options": ["false", "true"],
            "default": "false",
            "option_labels": {"false": "否", "true": "是"},
            "placeholder": "只生成重命名预览（items/preview 输出），不实际改动文件",
        },
    ],
    "outputs": [
        {"name": "output_dir", "type": "string"},
        {"name": "count", "type": "number"},
        {"name": "unchanged", "type": "number"},
        {"name": "skipped", "type": "number"},
        {"name": "failed", "type": "number"},
        {"name": "paths", "type": "array"},
        {
            "name": "errors",
            "type": "array",
            "itemType": "object",
            "canvas": False,
            "fields": {"image": "string", "error": "string"},
        },
        {
            "name": "items",
            "type": "array",
            "itemType": "object",
            "canvas": False,
            "fields": {
                "old": "string",
                "new": "string",
                "name": "string",
                "status": "string",
                "recognized": "string",
                "error": "string",
            },
        },
        {"name": "preview", "type": "string"},
    ],
}

# 批量模式下扫描的图片扩展名
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}

TEMPLATE_KEYS = ("name", "n", "width", "height", "date", "time", "parent", "text", "ai")
_INT_FIELDS = {"n", "width", "height"}
_TEMPLATE_HINT = "、".join("{" + k + "}" for k in TEMPLATE_KEYS)
_FORMATTER = Formatter()

# Windows 文件名非法字符（含控制字符，覆盖换行）与保留设备名
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

_PREVIEW_LIMIT = 100


def _to_int(value: Any, default: int) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _sanitize_stem(raw: str, max_len: int) -> str:
    """清理为 Windows 合法文件名主干：非法字符与空白折叠为 _，去首尾点空格。"""
    s = _ILLEGAL_CHARS.sub("_", str(raw or ""))
    s = re.sub(r"\s+", "_", s)
    s = s.strip(" ._")
    if not s:
        return ""
    if s.upper() in _RESERVED:
        s = f"_{s}"
    if max_len > 0 and len(s) > max_len:
        s = s[:max_len].rstrip(" ._")
    return s


def _clean_ai_text(raw: str) -> str:
    """AI 回复取第一行，剥掉引号与空白。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    s = s.splitlines()[0].strip()
    return s.strip("「」『』“”\"'`* ").strip()


def _default_ai_prompt(max_len: int) -> str:
    limit = max_len if max_len > 0 else 20
    return (
        f"看图给这张图片取一个简短的文件名：直接输出名称本身，"
        f"不要解释、不要引号、不要扩展名，不超过{limit}个字符。"
    )


def _validate_template(template: str, recognize_mode: str) -> None:
    """校验占位符白名单、识别依赖与格式说明符合法性。"""
    try:
        parsed = list(_FORMATTER.parse(template))
    except ValueError as exc:
        raise ValueError(f"命名规则花括号不匹配：{exc}") from exc
    for _literal, field, spec, _conv in parsed:
        if field is None:
            continue
        if field not in TEMPLATE_KEYS:
            raise ValueError(
                f"命名规则包含不支持的占位符 {{{field}}}，可用：{_TEMPLATE_HINT}"
            )
        if field == "text" and recognize_mode != "ocr":
            raise ValueError("命名规则使用了 {text}：请把「内容识别」设为 OCR 文字识别")
        if field == "ai" and recognize_mode != "ai":
            raise ValueError("命名规则使用了 {ai}：请把「内容识别」设为 AI 内容识别")
        if spec:
            dummy = 1 if field in _INT_FIELDS else "示例"
            try:
                format(dummy, spec)
            except ValueError as exc:
                raise ValueError(f"占位符 {{{field}:{spec}}} 格式无效：{exc}") from exc


def _apply_index_padding(template: str, digits: int) -> str:
    """给不带格式的 {n} 注入补零位数；用户手写的 {n:03d} 保持原样。"""
    if digits <= 0:
        return template
    parts: list[str] = []
    for literal, field, spec, conv in _FORMATTER.parse(template):
        piece = literal
        if field is not None:
            if field == "n" and not spec:
                spec = f"0{digits}d"
            inner = field
            if conv:
                inner += f"!{conv}"
            if spec:
                inner += f":{spec}"
            piece += "{" + inner + "}"
        parts.append(piece)
    return "".join(parts)


def _render_template(template: str, values: dict[str, Any]) -> str:
    try:
        return template.format(**values)
    except (KeyError, IndexError) as exc:
        raise ValueError(f"命名规则占位符无效：{exc}") from exc
    except ValueError as exc:
        raise ValueError(f"命名规则格式无效：{exc}") from exc


def _collect_images(src: Path) -> list[Path]:
    if src.is_file():
        return [src]
    files = sorted(
        p for p in src.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    if not files:
        raise ValueError(
            f"文件夹中未找到图片（支持 {'、'.join(sorted(IMAGE_EXTS))}）: {src}"
        )
    return files


def _image_size(path: Path) -> tuple[int, int]:
    """读取图片宽高；解码失败不阻断重命名，返回 (0, 0)。"""
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.size
    except Exception:
        return (0, 0)


def _ocr_pick_text(path: Path, pick: str) -> str:
    """对单张图片跑 OCR 并按策略取文本（复用 OCR 取字积木的引擎与会话）。"""
    from backend.blocks.ocr_recognize import run_ocr

    res = run_ocr(
        {"source_mode": "image", "image_path": str(path), "min_confidence": 0.3}
    )
    boxes = [
        b for b in (res.get("boxes") or []) if str(b.get("text") or "").strip()
    ]
    if not boxes:
        return ""
    if pick == "join":
        return "_".join(str(b["text"]).strip() for b in boxes)
    if pick == "longest":
        return str(max(boxes, key=lambda b: len(str(b["text"])))["text"])
    first = min(
        boxes, key=lambda b: (float(b.get("top") or 0), float(b.get("left") or 0))
    )
    return str(first["text"])


def _image_b64_jpeg(path: Path, max_side: int = 1024) -> str:
    """图片压成 JPEG Base64（视觉模型输入），过大先等比缩小。"""
    from PIL import Image

    with Image.open(path) as img:
        rgb = img.convert("RGB")
        rgb.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        rgb.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _parse_error_message(status_code: int, payload: dict[str, Any] | None) -> str:
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str):
            return err
        if payload.get("message"):
            return str(payload["message"])
    return f"HTTP {status_code}"


def _ai_name(
    path: Path, ai_cfg: dict[str, str], prompt: str, timeout_s: float
) -> str:
    """调用 OpenAI 兼容 /chat/completions 视觉接口，返回模型给出的命名。"""
    b64 = _image_b64_jpeg(path)
    url = ai_cfg["base_url"].rstrip("/")
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if ai_cfg["api_key"]:
        headers["Authorization"] = f"Bearer {ai_cfg['api_key']}"
    body = {
        "model": ai_cfg["model"],
        "temperature": 0.2,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            }
        ],
    }
    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=timeout_s)
    except httpx.HTTPError as exc:
        raise ValueError(f"AI 命名请求失败: {exc}") from exc
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    if resp.status_code != 200:
        raise ValueError(
            f"AI 命名失败（{_parse_error_message(resp.status_code, payload)}）"
        )
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("AI 命名响应格式异常：缺少 choices[0].message.content") from exc
    return str(content or "")


def _target_occupied(target: Path, source: Path, copy_mode: bool, used: set[str]) -> bool:
    if str(target).lower() in used:
        return True
    if not target.exists():
        return False
    # 原地重命名且目标就是自己（原名未变）不算占用
    return not (not copy_mode and target == source)


def _resolve_target(
    target: Path, source: Path, copy_mode: bool, conflict: str, used: set[str]
) -> tuple[Path, bool]:
    """解析目标路径冲突，返回 (最终路径, 目标是否仍被占用)。"""
    if not _target_occupied(target, source, copy_mode, used):
        return target, False
    if conflict == "rename":
        stem, ext = target.stem, target.suffix
        for k in range(2, 1000):
            cand = target.with_name(f"{stem}_{k}{ext}")
            if not _target_occupied(cand, source, copy_mode, used):
                return cand, False
        raise ValueError(f"无法为 {target.name} 找到不冲突的文件名")
    # skip / overwrite：目标不变，是否占用由调用方按模式处理
    return target, True


def _execute_in_place(plan: list[dict], conflict: str, errors: list[dict]) -> None:
    """两段式原地重命名：先全部改临时名释放旧名，再落到最终名。

    避免批次内 A 的目标名是 B 的旧名时互相覆盖（覆盖模式下会污染内容）。
    """
    import uuid

    moves = [it for it in plan if it["status"] == "planned"]
    temps: list[tuple[Path, Path, Path]] = []
    try:
        for idx, item in enumerate(moves):
            old = Path(item["old"])
            temp = old.with_name(
                f"__nexuz_tmp_{uuid.uuid4().hex[:8]}_{idx}{old.suffix}"
            )
            old.rename(temp)
            temps.append((temp, Path(item["new"]), old))
    except Exception as exc:
        for temp, _new, old in temps:
            try:
                temp.rename(old)
            except Exception:
                pass
        raise ValueError(f"重命名准备阶段失败（已还原原状）: {exc}") from exc

    for temp, new, old in temps:
        try:
            if conflict == "overwrite" and new.exists():
                os.replace(temp, new)
            else:
                temp.rename(new)
        except Exception as exc:
            errors.append({"image": str(old), "error": f"重命名失败: {exc}"})
            try:
                temp.rename(old)
            except Exception as restore_exc:
                errors.append(
                    {
                        "image": str(old),
                        "error": f"还原失败，文件保留为临时名 {temp.name}: {restore_exc}",
                    }
                )


def _execute_copy(plan: list[dict], errors: list[dict]) -> None:
    for item in plan:
        if item["status"] != "planned":
            continue
        old, new = Path(item["old"]), Path(item["new"])
        try:
            shutil.copy2(old, new)
        except Exception as exc:
            errors.append({"image": str(old), "error": f"复制失败: {exc}"})
            item["status"] = "failed"
            item["error"] = str(exc)


def _status_label(status: str) -> str:
    return {
        "renamed": "已重命名",
        "unchanged": "未变化",
        "skipped": "跳过（目标已存在）",
        "preview": "预览",
        "failed": "失败",
    }.get(status, status)


def handler(params, context, **kwargs):
    image_path = str(params.get("image_path") or "").strip()
    if not image_path:
        raise ValueError("请指定 image_path 图片路径（支持文件或文件夹）")
    src = Path(image_path)
    if not src.exists():
        raise FileNotFoundError(f"路径不存在: {src}")

    template = str(params.get("name_template") or "").strip()
    if not template:
        raise ValueError("请填写命名规则，如 game_{n} 或 {name}_{text}")

    recognize_mode = str(params.get("recognize_mode") or "none").strip() or "none"
    _validate_template(template, recognize_mode)

    # 识别依赖预检：环境问题一次性报错，避免批量中每张图都失败
    if recognize_mode == "ocr":
        from backend.blocks import ocr_recognize as _ocr_mod

        _ocr_mod._get_ocr()  # 预构建引擎，依赖缺失时给出明确报错
    ai_cfg: dict[str, str] | None = None
    timeout_s = 60.0
    if recognize_mode == "ai":
        cfg = get_ai_config()
        base_url = str(cfg.base_url or "").strip()
        model = str(cfg.model or "").strip()
        if not base_url or not model:
            raise ValueError(
                "未配置聊天模型：请在 设置 → Nexuz AI 填写 Base URL 与模型 ID"
                "（需支持图像输入的多模态模型，如 gpt-4o / qwen-vl / glm-4v）"
            )
        ai_cfg = {
            "base_url": base_url,
            "api_key": str(cfg.api_key or "").strip(),
            "model": model,
        }
        timeout_s = max(10.0, _to_float(params.get("timeout_s"), 60.0))

    files = _collect_images(src)
    max_len = max(0, _to_int(params.get("text_max_len"), 20))
    digits = max(0, min(6, _to_int(params.get("index_digits"), 2)))
    start = max(0, _to_int(params.get("start_index"), 1))
    conflict = str(params.get("conflict_mode") or "rename").strip() or "rename"
    dry_run = str(params.get("dry_run") or "false").strip().lower() == "true"
    ocr_pick = str(params.get("ocr_line") or "first").strip() or "first"

    out_dir_raw = str(params.get("output_dir") or "").strip()
    copy_mode = bool(out_dir_raw)
    dest_root: Path | None = None
    if copy_mode:
        dest_root = Path(out_dir_raw)
        if dest_root.resolve() == files[0].parent.resolve():
            copy_mode = False  # 输出目录与源相同 → 等同原地重命名
        else:
            dest_root.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    base_values = {
        "date": now.strftime("%Y%m%d"),
        "time": now.strftime("%H%M%S"),
    }
    eff_template = _apply_index_padding(template, digits)
    ai_prompt = str(params.get("ai_prompt") or "").strip() or _default_ai_prompt(max_len)

    used: set[str] = set()
    plan: list[dict] = []
    errors: list[dict] = []

    for i, f in enumerate(files):
        values: dict[str, Any] = dict(base_values)
        values["name"] = f.stem
        values["n"] = start + i
        values["parent"] = f.parent.name
        values["width"], values["height"] = _image_size(f)

        recognized = ""
        if recognize_mode == "ocr":
            try:
                raw = _ocr_pick_text(f, ocr_pick)
            except Exception as exc:  # noqa: BLE001 — 单张识别失败不中断批量
                errors.append({"image": str(f), "error": f"OCR 识别失败: {exc}"})
                continue
            recognized = _sanitize_stem(raw, max_len) or f.stem
            values["text"] = recognized
        elif recognize_mode == "ai":
            try:
                raw = _ai_name(f, ai_cfg, ai_prompt, timeout_s)
            except Exception as exc:  # noqa: BLE001
                errors.append({"image": str(f), "error": str(exc)})
                continue
            recognized = _sanitize_stem(_clean_ai_text(raw), max_len) or f.stem
            values["ai"] = recognized

        # 渲染结果统一过 sanitize：模板字面量或任意占位符都可能带非法字符
        stem = _sanitize_stem(_render_template(eff_template, values), 0) or f.stem
        target_dir = dest_root if copy_mode else f.parent
        target = target_dir / f"{stem}{f.suffix}"
        final, occupied = _resolve_target(target, f, copy_mode, conflict, used)
        used.add(str(final).lower())

        if not copy_mode and final == f:
            status = "unchanged"
        elif occupied and conflict == "skip":
            status = "skipped"
        elif dry_run:
            status = "preview"
        else:
            status = "planned"
        plan.append(
            {
                "old": str(f),
                "new": str(final),
                "name": final.stem,
                "status": status,
                "recognized": recognized,
            }
        )

    if not dry_run:
        if copy_mode:
            _execute_copy(plan, errors)
        else:
            _execute_in_place(plan, conflict, errors)
        failed_images = {e["image"] for e in errors}
        for item in plan:
            if item["status"] == "planned":
                item["status"] = (
                    "failed" if item["old"] in failed_images else "renamed"
                )

    count = sum(1 for it in plan if it["status"] == "renamed")
    unchanged = sum(1 for it in plan if it["status"] == "unchanged")
    skipped = sum(1 for it in plan if it["status"] == "skipped")
    for item in plan:
        if item["status"] == "failed":
            item["error"] = next(
                (e["error"] for e in errors if e["image"] == item["old"]), ""
            )

    paths = [
        it["new"] for it in plan if it["status"] in ("renamed", "unchanged")
    ]
    lines = [
        f"{Path(it['old']).name} → {Path(it['new']).name}（{_status_label(it['status'])}）"
        for it in plan
    ]
    if len(lines) > _PREVIEW_LIMIT:
        lines = lines[:_PREVIEW_LIMIT] + [f"…（其余 {len(plan) - _PREVIEW_LIMIT} 条见 items 输出）"]
    preview = "\n".join(lines)

    out_root = dest_root if copy_mode else files[0].parent
    return {
        "output_dir": str(out_root.resolve()),
        "count": count,
        "unchanged": unchanged,
        "skipped": skipped,
        "failed": len(errors),
        "paths": paths,
        "errors": errors,
        "items": plan,
        "preview": preview,
    }
