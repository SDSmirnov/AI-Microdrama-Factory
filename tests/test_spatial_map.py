"""Item 8a: per-(scene, location) spatial map constant.

From already-stored anchor JSONs only: compass line derived from the view
slug (camera side = 180-degree boundary, per anchor-JSON axes), landmark
list from anchor_points object labels/ids, one disposition line per panel
deduplicated by anchor name. Pasted verbatim as SPATIAL BLOCKING's first
line in every clip prompt of the scene. No anchor JSON -> omitted, one
log line. Computed in memory; no metadata writes.
"""
import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.animation.prompt_builder import RefBite, build_spatial_map, \
    build_video_prompt

AXES = ("Normalized [0,1]. X: 0=image-left (West), 1=image-right (East). "
        "Y: 0=entrance/south (village side), 1=far/north (seaward embrasure). "
        "View-Primary (camera faces North/primary): lateral=X, depth=Y. "
        "View-To-Entrance/View-Opposite (camera at north embrasure facing "
        "South): x_mirrored=1-x (LEFT/RIGHT SWAP), depth reversed.")

ANCHOR_JSON = {
    "name": "Observation-Post-View-Primary",
    "anchor_points": {
        "axes": AXES,
        "objects": [
            {"id": "plywood-dirt-floor", "label": "floor"},
            {"id": "seaward-embrasure-lip", "label": "lip"},
            {"id": "east-sandbag-stack", "label": "stack"},
        ],
    },
}
SIBLING_JSON = dict(ANCHOR_JSON)  # populated variant of the same location


class _StubCatalog:
    """Duck-typed _RefCatalog: .info (slug -> json) + .lookup(slug)."""

    def __init__(self, info):
        self.info = info

    def lookup(self, slug):
        key = slug.lower()
        return self.info.get(key), None


def _scene(refs, dispositions):
    return {"scene_id": 1, "panels": [
        {"panel_index": i + 1, "location_references": [refs[i]],
         "visual_disposition": dispositions[i],
         "state": {"actors": []}}
        for i in range(len(refs))
    ]}


def _dispo_lines(text):
    """Disposition lines only (they start with a bracketed anchor key);
    the GEOMETRY and Landmarks lines are not disposition lines."""
    return [l for l in text.splitlines()
            if l.startswith("[") and " — " in l]


class SpatialMapTests(unittest.TestCase):
    def setUp(self):
        self.catalog = _StubCatalog({
            "observation-post-view-primary": ANCHOR_JSON,
            "observation-post-view-opposite": {"name": "x"},  # empty variant
        })

    def test_compass_from_variant_view_slug(self):
        scene = _scene(["Observation-Post-View-Opposite"] * 2, ["", ""])
        text = build_spatial_map(scene, self.catalog)
        compass = text.splitlines()[0]
        self.assertIn("Observation-Post-View-Opposite", compass)
        self.assertIn("View-Opposite", compass)          # variant sentence used
        self.assertIn("x_mirrored", compass)

    def test_primary_view_uses_base_axes_mapping(self):
        scene = _scene(["Observation-Post-View-Primary"], [""])
        text = build_spatial_map(scene, self.catalog)
        compass = text.splitlines()[0]
        self.assertIn("image-left", compass)
        self.assertNotIn("x_mirrored", compass.splitlines()[0])

    def test_landmarks_from_anchor_points_objects(self):
        scene = _scene(["Observation-Post-View-Primary"], [""])
        text = build_spatial_map(scene, self.catalog)
        landmarks = [l for l in text.splitlines() if "Landmarks" in l][0]
        for anchor in ("plywood-dirt-floor", "seaward-embrasure-lip",
                       "east-sandbag-stack"):
            self.assertIn(f"[{anchor}]", landmarks)

    def test_dispositions_deduplicated_by_anchor_name(self):
        scene = _scene(
            ["Observation-Post-View-Primary"] * 3,
            ["Lin stands at [seaward-embrasure-lip] on [plywood-dirt-floor]",
             "Lin stands at [seaward-embrasure-lip] pressed against wall",
             "Hu stands beside [east-sandbag-stack]"])
        text = build_spatial_map(scene, self.catalog)
        lines = text.splitlines()
        lip = [l for l in lines if l.startswith("[seaward-embrasure-lip]")]
        self.assertEqual(len(lip), 1)
        self.assertIn("Lin stands at", lip[0])  # first panel wins
        self.assertNotIn("pressed against wall", text)
        self.assertTrue(any(l.startswith("[east-sandbag-stack]")
                            for l in lines))

    def test_disposition_line_is_not_repeated_per_anchor(self):
        """Regression: the disposition body must appear ONCE per sentence.

        The bug: one line per anchor, each carrying the whole paragraph as
        its body — a paragraph with N anchors produced N identical copies
        of the same prose (10x in the real CRAB scene-3 panel 1).
        """
        scene = _scene(
            ["Observation-Post-View-Primary"],
            ["Lin stands at [seaward-embrasure-lip] on [plywood-dirt-floor]. "
             "Hu stands beside [east-sandbag-stack] on [plywood-dirt-floor]."])
        text = build_spatial_map(scene, self.catalog)
        bodies = [l.split("— ", 1)[1] for l in _dispo_lines(text)]
        self.assertEqual(len(bodies), 2)          # one line per sentence
        self.assertEqual(len(set(bodies)), 2)     # and no body repeats
        self.assertNotIn("Lin stands at [seaward-embrasure-lip] on "
                         "[plywood-dirt-floor]. Hu stands", text)

    def test_multiple_anchors_in_one_sentence_share_one_line(self):
        scene = _scene(
            ["Observation-Post-View-Primary"],
            ["Lin stands braced at [seaward-embrasure-lip] above "
             "[east-sandbag-stack] with the rifle on [plywood-dirt-floor]."])
        text = build_spatial_map(scene, self.catalog)
        dispo = _dispo_lines(text)
        self.assertEqual(len(dispo), 1)          # one sentence, one line
        for name in ("seaward-embrasure-lip", "east-sandbag-stack",
                     "plywood-dirt-floor"):
            self.assertIn(f"[{name}]", dispo[0])  # all keys present
        self.assertIn("stands braced at", dispo[0])

    def test_long_sentence_clipped_at_word_boundary(self):
        long_text = ("Lin crouches on his haunches at [rubble-threshold] "
                     "inside [jagged-brick-edges] facing [street-mouth] while "
                     "the heavy [gate-door] swings and dust rolls over "
                     "[rubble-threshold] and [street-mouth] again and again "
                     "for a very long time indeed and the light dies slowly "
                     "behind the ruined wall until nothing remains but the "
                     "ash and the sound of the gate moving on its hinges in "
                     "the dark and the dust settling down at last on every "
                     "stone and stone and stone of the ruined street")
        scene = _scene(["Observation-Post-View-Primary"], [long_text])
        text = build_spatial_map(scene, self.catalog)
        body = _dispo_lines(text)[0].split("— ", 1)[1]
        self.assertLessEqual(len(body), 421)
        self.assertTrue(body.endswith("…"))
        self.assertNotIn("  ", body[:-1][-3:])  # cut at a word edge

    def test_populated_sibling_used_when_variant_json_empty(self):
        scene = _scene(["Observation-Post-View-Opposite"], [""])
        text = build_spatial_map(scene, self.catalog)
        self.assertIn("[plywood-dirt-floor]", text)  # landmarks found anyway

    def test_no_anchor_json_omitted_with_log(self):
        catalog = _StubCatalog({"hall-view-primary": {"name": "Hall"}})
        scene = _scene(["Hall-View-Primary"], [""])
        with self.assertLogs(level=logging.INFO) as logs:
            text = build_spatial_map(scene, catalog)
        self.assertEqual(text, "")
        self.assertTrue(any("anchor" in o.lower() for o in logs.output))

    def test_map_is_first_line_of_spatial_blocking(self):
        scene = _scene(["Observation-Post-View-Primary"], [""])
        smap = build_spatial_map(scene, self.catalog)
        panel = _scene(["Observation-Post-View-Primary"], [""])[
            "panels"][0]
        panel["visual_start"] = "[SCALE] MS 35mm eye-level cam@[wall]"
        refs = [RefBite("<IMAGE_0>", None, "first_frame", "f", ""),
                RefBite("<IMAGE_1>", None, "location",
                        "Observation-Post-View-Primary", "a post")]
        prompt = build_video_prompt(panel, refs, [], 4, spatial_map=smap)
        block = prompt.split("SPATIAL BLOCKING:")[1].split("OPTICS:")[0]
        first = block.strip().splitlines()[0]
        self.assertIn("GEOMETRY", first)  # map pasted verbatim, first line
        self.assertIn("[SCALE] MS 35mm", block)  # panel's own lines follow

    def test_panel_disposition_not_repeated_when_map_already_states_it(self):
        """The map is built from the first mention of each anchor, so for
        that panel the map already carries the sentence; the panel's own
        'Disposition:' line must not paste it a second time."""
        dispo = ("Lin stands at [seaward-embrasure-lip] on [plywood-dirt-floor]. "
                 "Hu stands beside [east-sandbag-stack].")
        scene = _scene(["Observation-Post-View-Primary"], [dispo])
        smap = build_spatial_map(scene, self.catalog)
        panel = scene["panels"][0]
        panel["visual_start"] = "[SCALE] MS 35mm eye-level cam@[wall]"
        refs = [RefBite("<IMAGE_0>", None, "first_frame", "f", ""),
                RefBite("<IMAGE_1>", None, "location",
                        "Observation-Post-View-Primary", "a post")]
        prompt = build_video_prompt(panel, refs, [], 4, spatial_map=smap)
        self.assertNotIn("Disposition:", prompt)   # fully covered
        self.assertEqual(prompt.count("Lin stands at [seaward-embrasure-lip]"), 1)

    def test_panel_disposition_kept_when_map_does_not_cover_it(self):
        scene = _scene(["Observation-Post-View-Primary"], [""])
        smap = build_spatial_map(scene, self.catalog)
        panel = scene["panels"][0]
        panel["visual_disposition"] = "Hu stands beside [east-sandbag-stack]."
        panel["visual_start"] = "[SCALE] MS 35mm eye-level cam@[wall]"
        refs = [RefBite("<IMAGE_0>", None, "first_frame", "f", "")]
        prompt = build_video_prompt(panel, refs, [], 4, spatial_map=smap)
        self.assertIn("Disposition: Hu stands beside [east-sandbag-stack].",
                      prompt)

    def test_empty_map_keeps_spatial_blocking_unchanged(self):
        panel = {"panel_index": 1, "location_references": [],
                 "visual_disposition": "",
                 "visual_start": "[SCALE] MS 35mm eye-level cam@[wall]",
                 "state": {"actors": []}}
        refs = [RefBite("<IMAGE_0>", None, "first_frame", "f", "")]
        prompt = build_video_prompt(panel, refs, [], 4, spatial_map="")
        self.assertNotIn("GEOMETRY", prompt)


if __name__ == "__main__":
    unittest.main()
