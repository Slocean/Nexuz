from __future__ import annotations

from pathlib import Path
from time import strftime

from backend.blocks._helpers import grab_region, validate_region

SCHEMA = {
    "type": "screenshot",
    "label": "区域截图",
    "category": "识别类",
    "inputs": [
        {
            "name": "region",
            "type": "rect",
            "label": "截图区域",
            "default": None,
        },
        {
            "name": "save_path",
            "type": "string",
            "label": "保存路径(可选，空则自动)",
            "default": "",
        },
    ],
    "outputs": [
        {"name": "path", "type": "string"},
        {"name": "width", "type": "number"},
        {"name": "height", "type": "number"},
    ],
}


def handler(params, context, **kwargs):
    region = params.get("region")
    if not region:
        raise ValueError("截图需要指定 region [x1,y1,x2,y2]，请先框选区域")
    x1, y1, x2, y2 = validate_region(region)
    img = grab_region(x1, y1, x2, y2)

    save_path = str(params.get("save_path") or "").strip()
    if save_path:
        out = Path(save_path)
        out.parent.mkdir(parents=True, exist_ok=True)
    else:
        shots = Path(__file__).resolve().parent.parent.parent / "screenshots"
        shots.mkdir(parents=True, exist_ok=True)
        out = shots / f"shot_{strftime('%Y%m%d_%H%M%S')}.png"

    if out.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp"):
        out = out.with_suffix(".png")
    img.save(out)
    return {"path": str(out.resolve()), "width": img.width, "height": img.height}
