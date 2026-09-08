import importlib.util
from pathlib import Path
import pytest
from PIL import Image

PLUGIN = Path(__file__).resolve().parents[1] / "examples" / "user_blocks" / "sheet_segment.py"

def _load():
    spec = importlib.util.spec_from_file_location("ss_min", PLUGIN)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    sys_mod = _load()
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    import test_sheet_segment_plugin as t
    root = tmp_path_factory.mktemp("min_repro")
    sheets = [t._sheet(root / "sheetA.png"), t._sheet(root / "sheetB.png")]
    return t, sys_mod, root, sheets

def test_min(scene):
    t, m, root, sheets = scene
    result = m.handler({"image_path": "\n".join(str(s) for s in sheets), "output_dir": str(root / "out")}, {})
    for p in result["paths"][:8]:
        print('READ', Path(p).name, Path(p).parent.name, Image.open(p).size)
    for f in sorted((root / "out" / "sheetA" / "down").glob("down_*.png")):
        print('GLOB', f.name, Image.open(f).size)
