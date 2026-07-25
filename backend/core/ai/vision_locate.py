"""Multimodal screenshot locate → point_ref (Pathway A)."""

from __future__ import annotations

import base64
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.core.ai.lc.models import create_chat_model
from backend.core.ai.locate import pack_point_artifact
from backend.core.ai.types import AiConfig


class VisionPoint(BaseModel):
    x: float = Field(description="像素 X（相对截图左上）")
    y: float = Field(description="像素 Y（相对截图左上）")
    label: str = Field(default="", description="命中目标简述")
    confidence: float = Field(default=0.5, ge=0, le=1)


def _data_url_to_parts(data_url: str) -> tuple[str, str]:
    """Return (mime, base64_payload)."""
    m = re.match(r"data:([^;]+);base64,(.+)", data_url or "", re.I | re.S)
    if not m:
        raise ValueError("截图不是 data_url")
    return m.group(1), m.group(2)


def locate_on_screenshot_vision(
    artifacts: dict[str, Any],
    *,
    query: str,
    shot_ref: str | None = None,
    cfg: AiConfig | None = None,
) -> dict[str, Any]:
    """
    Use multimodal model to find a UI target on a captured screenshot.
    Writes point into artifacts['points'] and returns point_ref.
    """
    shots = artifacts.get("shots") if isinstance(artifacts.get("shots"), dict) else {}
    if not shots:
        return {"ok": False, "error": "无截图，请先 capture_screen"}
    if shot_ref and shot_ref in shots:
        shot = shots[shot_ref]
    else:
        shot = max(shots.values(), key=lambda s: float(s.get("created_at") or 0))
    if not isinstance(shot, dict) or not shot.get("data_url"):
        return {"ok": False, "error": "截图缺少 data_url"}

    data_url = str(shot["data_url"])
    left = float(shot.get("left") or 0)
    top = float(shot.get("top") or 0)

    try:
        llm = create_chat_model(cfg, temperature=0, streaming=False)
        structured = llm.with_structured_output(VisionPoint)
        mime, _b64 = _data_url_to_parts(data_url)
        msg = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": (
                        f"在截图中找到目标并给出中心像素坐标（相对截图左上角）。"
                        f"目标：{query}\n只输出一个最可能的点。"
                    ),
                },
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
        )
        result = structured.invoke(
            [
                SystemMessage(
                    content="你是 UI 定位器。根据截图返回目标中心坐标 x,y（像素）。"
                ),
                msg,
            ]
        )
        pt = result if isinstance(result, VisionPoint) else VisionPoint.model_validate(result)
    except Exception as exc:
        return {"ok": False, "error": f"多模态定位失败: {exc}", "fallback": "ocr"}

    abs_x = int(round(left + float(pt.x)))
    abs_y = int(round(top + float(pt.y)))
    packed = pack_point_artifact(
        artifacts,
        x=abs_x,
        y=abs_y,
        label=pt.label or query,
        source="vision",
    )
    if not packed.get("ok"):
        return packed
    return {
        **packed,
        "query": query,
        "confidence": pt.confidence,
        "source": "vision",
        "shot_id": shot.get("shot_id"),
    }


_VISION_MODEL_MARKERS = (
    "gpt-4o",
    "gpt-4.1",
    "claude-3",
    "claude-4",
    "gemini",
    "qwen-vl",
    "qwen2-vl",
    "qwen2.5-vl",
    "llava",
    "vision",
    "pixtral",
    "glm-4v",
    "internvl",
)


def infer_supports_vision(model: str) -> bool:
    name = (model or "").strip().lower()
    return any(m in name for m in _VISION_MODEL_MARKERS)
