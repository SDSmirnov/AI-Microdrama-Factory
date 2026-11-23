"""Unit tests for the reference assembler (Item 2, GROK-VIDEO-PLAN).

assemble_refs() turns panel metadata into an ordered list of RefBite:
<IMAGE_0> = first frame (uncapped), then location refs, then in-frame
characters (or panel["references"] when no state), budget-capped with
logged drops. Pure file/meta logic — no network.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.animation.refs import RefBite, assemble_refs
from lib.core.project import Project


class RefHarness(unittest.TestCase):
    """Common fixture: a ref dir with PNGs/JSONs plus a Project over it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ref_dir = Path(self.tmp.name) / "refs"
        self.panels_dir = Path(self.tmp.name) / "panels"
        self.ref_dir.mkdir()
        self.panels_dir.mkdir()

        self.project = Project()
        self.project.ref_dir = self.ref_dir
        self.project.character_info = {}
        self.project.character_images = {}

        # Ref catalog: two characters, one prop, two room views (one
        # non-canonical file only), plus a character variation with no PNG.
        self._add_ref("Reporter", type="Character", vvd="Reporter in gray suit holding a mic.")
        self._add_ref("Groom", type="Character", vvd="Groom in black tuxedo, white rose.")
        self._add_ref("Bride", type="Character", vvd="Bride in white gown, veil up.")
        self._add_ref("Bride-Gown", type="Character", vvd="Bride in red gown.", png=False)
        self._add_ref("Wedding-Bouquet", type="Object", vvd="White and rose bouquet.")
        self._add_ref("Mansion-Hall-View-From-Entrance", type="Room",
                      vvd="Mansion hall seen from the doors.",
                      extra={"anchor_points": {"objects": [{"label": "stairs"}]}})
        # View-To-Entrance is canonicalized to View-From-Entrance: no own file.
        self._add_ref("Mansion-Hall-View-To-Entrance", type="Room",
                      vvd="Mansion hall seen towards the doors.", png=False)

        self.scene = {"scene_id": 1}
        self.panel = {
            "panel_index": 3,
            "references": [],
            "location_references": [],
            "state": None,
        }

    def _add_ref(self, name, type="Character", vvd="", png=True, extra=None):
        slug = name.lower()
        info = {"name": name, "type": type, "video_visual_desc": vvd,
                "visual_desc": f"{vvd} Wide shot.", **(extra or {})}
        self.project.character_info[name] = info
        data = json.dumps(info)
        if png:
            (self.ref_dir / f"{slug}.json").write_text(data)
            (self.ref_dir / f"{slug}.png").write_bytes(b"PNG" + name.encode())
            self.project.character_images[name] = str(self.ref_dir / f"{slug}.png")
        else:
            (self.ref_dir / f"{slug}.json").write_text(data)

    def _panel_png(self):
        return self.panels_dir / "001_03_static.png"


class FirstFrameTests(RefHarness):
    def test_first_frame_gets_image_0_uncapped(self):
        self._panel_png().write_bytes(b"PNGframe")
        bites = assemble_refs(self.panel, self.scene, self.panels_dir,
                              self.project, max_refs=1)
        first = bites[0]
        self.assertIsInstance(first, RefBite)
        self.assertEqual(first.tag, "<IMAGE_0>")
        self.assertEqual(first.role, "first_frame")
        self.assertEqual(first.png, self._panel_png())
        # Uncapped: first frame exists even though max_refs=1 leaves no slot.
        self.assertEqual(len(bites), 1)

    def test_missing_first_frame_dropped_not_fatal(self):
        bites = assemble_refs(self.panel, self.scene, self.panels_dir,
                              self.project, max_refs=2)
        self.assertEqual([b.role for b in bites if b.role == "first_frame"], [])


class LocationTests(RefHarness):
    def setUp(self):
        super().setUp()
        self._panel_png().write_bytes(b"PNGframe")
        self.panel["location_references"] = ["Mansion-Hall-View-To-Entrance"]

    def test_noncanonical_view_suffix_falls_back_to_canonical_png(self):
        bites = assemble_refs(self.panel, self.scene, self.panels_dir,
                              self.project, max_refs=5)
        locs = [b for b in bites if b.role == "location"]
        self.assertEqual(len(locs), 1)
        self.assertEqual(locs[0].png.name, "mansion-hall-view-from-entrance.png")
        self.assertEqual(locs[0].tag, "<IMAGE_1>")
        self.assertIn("Mansion hall seen from the doors", locs[0].descriptor)

    def test_unknown_location_dropped(self):
        self.panel["location_references"] = ["No-Such-Room-View-Primary"]
        bites = assemble_refs(self.panel, self.scene, self.panels_dir,
                              self.project, max_refs=5)
        self.assertEqual([b.name for b in bites if b.role == "location"], [])


class StateActorTests(RefHarness):
    def setUp(self):
        super().setUp()
        self._panel_png().write_bytes(b"PNGframe")
        self.panel["state"] = {"actors": [
            {"name": "Groom", "visual_ref": "Groom", "in_frame": True,
             "pose": "standing at the doors", "position": "top step of [stairs]",
             "gaze_target": "Reporter"},
            {"name": "Extra", "visual_ref": "Extra", "in_frame": False,
             "pose": "", "position": "", "gaze_target": None},
        ]}

    def test_in_frame_actor_tagged_off_frame_skipped(self):
        bites = assemble_refs(self.panel, self.scene, self.panels_dir,
                              self.project, max_refs=5)
        chars = [b for b in bites if b.role == "character"]
        self.assertEqual([b.name for b in chars], ["Groom"])
        self.assertEqual(chars[0].tag, "<IMAGE_1>")  # after first frame; no location ref in this panel

    def test_actor_descriptor_carries_ref_desc_and_state(self):
        bites = assemble_refs(self.panel, self.scene, self.panels_dir,
                              self.project, max_refs=5)
        desc = next(b for b in bites if b.name == "Groom").descriptor
        self.assertIn("Groom in black tuxedo", desc)
        self.assertIn("standing at the doors", desc)
        self.assertIn("top step of [stairs]", desc)
        self.assertIn("Reporter", desc)  # gaze target

    def test_variant_without_png_falls_back_to_primary_png(self):
        self.panel["state"]["actors"] = [
            {"name": "Bride", "visual_ref": "Bride-Gown", "in_frame": True,
             "pose": "walking", "position": "by the doors", "gaze_target": "Groom"},
        ]
        bites = assemble_refs(self.panel, self.scene, self.panels_dir,
                              self.project, max_refs=5)
        bride = next(b for b in bites if b.name == "Bride-Gown")
        self.assertEqual(bride.png.name, "bride.png")  # primary fallback
        # Descriptor still comes from the resolved ref JSON when present.
        self.assertIn("red gown", bride.descriptor)


class NoStateTests(RefHarness):
    def setUp(self):
        super().setUp()
        self._panel_png().write_bytes(b"PNGframe")
        self.panel["references"] = [
            "Mansion-Hall-View-To-Entrance", "Groom",
            "CN-NEWS-Microphone", "Wedding-Bouquet",
        ]

    def test_references_without_state_props_classified(self):
        # No location_references on the panel, but the references list
        # carries the room view slug -> location role via type inference.
        self._add_ref("CN-NEWS-Microphone", type="Object", vvd="News mic.")
        bites = assemble_refs(self.panel, self.scene, self.panels_dir,
                              self.project, max_refs=5)
        roles = {b.name: b.role for b in bites}
        self.assertEqual(roles.get("Mansion-Hall-View-To-Entrance"), "location")
        self.assertEqual(roles.get("Groom"), "character")
        self.assertEqual(roles.get("CN-NEWS-Microphone"), "prop")
        self.assertEqual(roles.get("Wedding-Bouquet"), "prop")

    def test_case_and_dash_tolerant_file_resolution(self):
        self.project.character_info["CN-NEWS-Microphone"] = {
            "name": "CN-NEWS-Microphone", "type": "Object",
            "video_visual_desc": "News mic.", "visual_desc": "News mic.",
        }
        (self.ref_dir / "cn-news-microphone.json").write_text(json.dumps(
            {"name": "CN-NEWS-Microphone", "type": "Object",
             "video_visual_desc": "News mic.", "visual_desc": "News mic."}))
        (self.ref_dir / "cn-news-microphone.png").write_bytes(b"PNG")
        self.panel["references"] = ["CN-NEWS-Microphone"]
        bites = assemble_refs(self.panel, self.scene, self.panels_dir,
                              self.project, max_refs=5)
        self.assertEqual(len(bites), 2)  # first frame + prop
        self.assertEqual(bites[1].png.name, "cn-news-microphone.png")


class BudgetTests(RefHarness):
    def setUp(self):
        super().setUp()
        self._panel_png().write_bytes(b"PNGframe")
        self.panel["references"] = ["Groom", "Reporter", "Wedding-Bouquet"]

    def test_budget_drops_lowest_priority_with_log(self):
        bites = assemble_refs(self.panel, self.scene, self.panels_dir,
                              self.project, max_refs=2)
        # First frame (free) + 2 budgeted: Groom, Reporter kept; prop dropped.
        names = [b.name for b in bites[1:]]
        self.assertEqual(names, ["Groom", "Reporter"])

    def test_first_frame_not_counted_against_budget(self):
        bites = assemble_refs(self.panel, self.scene, self.panels_dir,
                              self.project, max_refs=3)
        self.assertEqual(len(bites), 4)  # frame + 3 refs


class NoRefsTests(RefHarness):
    def test_empty_panel_returns_only_first_frame(self):
        self._panel_png().write_bytes(b"PNGframe")
        bites = assemble_refs(self.panel, self.scene, self.panels_dir,
                              self.project, max_refs=3)
        self.assertEqual([b.tag for b in bites], ["<IMAGE_0>"])

    def test_nothing_at_all_returns_empty_list(self):
        bites = assemble_refs(self.panel, self.scene, self.panels_dir,
                              self.project, max_refs=3)
        self.assertEqual(bites, [])


class RefBudgetTests(unittest.TestCase):
    def test_ref_budget_leaves_room_for_the_first_frame(self):
        from lib.animation.refs import default_max_refs
        from lib.llm.openrouter import VIDEO_MAX_REFS
        with mock.patch.dict(os.environ, {'AI_VIDEO_MAX_REFS': '99'}):
            self.assertEqual(1 + default_max_refs(), VIDEO_MAX_REFS)


if __name__ == "__main__":
    unittest.main()
