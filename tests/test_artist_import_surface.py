"""Names imported from ``lib.studio.artist`` must resolve to their implementations."""
import ast
import importlib
import importlib.util
import pkgutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.studio import artist

# Imported outside the package.
EXTERNAL_SURFACE = (
    "_ROOM_VIEWS",
    "_VIEW_CAMERA",
    "_anchor_id",
    "_anchor_visibility_block",
    "_build_image_prompt",
    "_build_panel_prompt",
    "_extract_camera_anchor_labels",
    "_is_wall_camera",
    "_load_entrance_anchor_points",
    "_panel_anchor_context",
    "_panel_camera_xy",
    "_panel_image_size",
    "_parse_room_dims",
    "_project_image_x",
    "_render_single_panel",
    "_render_single_ref",
    "_view_aspect_ratio",
    "_view_rig",
    "auto_cast_characters",
    "detail_room_refs",
    "export_image_prompt",
    "load_character_refs",
    "panel_anchor_block_enabled",
    "remake_room_refs",
    "render_character_refs",
    "render_extra_panel",
    "render_full_frame_panel",
    "render_panels",
    "render_scene_grids",
    "run_room_anchors",
)

class ExternalSurfaceTests(unittest.TestCase):
    def test_every_external_name_exists(self):
        missing = [name for name in EXTERNAL_SURFACE if not hasattr(artist, name)]
        self.assertEqual(missing, [])


class FacadeTests(unittest.TestCase):
    def test_reexports_every_submodule_definition(self):
        homes = {n: m for n, m in _defining_modules().items() if n != "logger"}
        self.assertEqual({n: m for n, m in homes.items() if len(m) != 1}, {})
        mismatched = [n for n, (m,) in homes.items()
                      if getattr(artist, n, None) is not getattr(importlib.import_module(m), n)]
        self.assertEqual(mismatched, [])


def _defining_modules():
    homes = {}
    for info in pkgutil.iter_modules(artist.__path__, f"{artist.__name__}."):
        tree = ast.parse(Path(importlib.util.find_spec(info.name).origin).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                targets = [node.name]
            elif isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target.id]
            else:
                continue
            for name in targets:
                homes.setdefault(name, []).append(info.name)
    return homes


if __name__ == "__main__":
    unittest.main()
