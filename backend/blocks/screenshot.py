from __future__ import annotations

from pathlib import Path
from time import strftime

from backend.blocks._helpers import grab_region, resolve_region_from_params

SCHEMA = {
    "type": "screenshot",
    "description": "截取屏幕区域为图片（留空=整个虚拟桌面），供找图/OCR/审计使用。",
    "label": "区域截图",
    "category": "识别类",
    "inputs": [
        {
            "name": "region",
            "type": "rect",
            "label": "截图区域（留空=整个虚拟桌面）",
            "default": None,
        },
        {
            "name": "save_path",
            "type": "string",
            "label": "保存路径",
            "default": "",
            "placeholder": "留空则自动保存",
        },
    ],
    "outputs": [
        {"name": "path", "type": "string"},
        {"name": "left", "type": "number"},
        {"name": "top", "type": "number"},
        {"name": "width", "type": "number"},
        {"name": "height", "type": "number"},
        {"name": "region", "type": "object", "canvas": False},
    ],
}


def handler(params, context, **kwargs):
    resolved = resolve_region_from_params(params)
    if not resolved:
        # 缺省抓整个虚拟桌面（多显示器含负坐标副屏），与 capture_screen 口径一致
        from backend.core.dpi import virtual_screen_rect

        resolved = virtual_screen_rect()
    x1, y1, x2, y2 = resolved
    img = grab_region(x1, y1, x2, y2)

    save_path = str(params.get("save_path") or "").strip()
    if save_path:
        out = Path(save_path)
        out.parent.mkdir(parents=True, exist_ok=True)
    else:
        from backend.paths import get_data_dir

        shots = get_data_dir(create=True) / "screenshots"
        shots.mkdir(parents=True, exist_ok=True)
        out = shots / f"shot_{strftime('%Y%m%d_%H%M%S')}.png"

    if out.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp"):
        out = out.with_suffix(".png")
    img.save(out)
    return {
        "path": str(out.resolve()),
        "left": int(x1),
        "top": int(y1),
        "width": img.width,
        "height": img.height,
        "region": [int(x1), int(y1), int(x2), int(y2)],
    }
