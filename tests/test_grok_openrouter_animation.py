"""Unit tests for GrokOpenRouterAnimator Item 4 wiring + DRY probe (probe 1).

run_all() assembles refs (Item 2), builds the prompt (Item 3), clamps the
duration to the model range, and sends refs/last_frame to the transport. With
DRY=1 it dumps the exact prompt + payload into the shared manual_llm dir and
calls nothing.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.animation.grok_openrouter import GrokOpenRouterAnimator
from lib.llm import manual as manual_mod

from support import StubLLM, make_ref_project


class Harness(unittest.TestCase):
    def setUp(self):
        self._orig_env = {k: os.environ.get(k) for k in
                          ("DRY", "AI_OPENROUTER_LAST_FRAME", "AI_VIDEO_MAX_REFS")}
        for k in ("DRY", "AI_OPENROUTER_LAST_FRAME", "AI_VIDEO_MAX_REFS"):
            os.environ.pop(k, None)

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_manual_dir = manual_mod._OUTPUT_DIR
        self.addCleanup(setattr, manual_mod, '_OUTPUT_DIR', self._orig_manual_dir)
        self.root = Path(self.tmp.name)
        self.ref_dir = self.root / "ref_thriller"
        self.panels_dir = self.root / "panels"
        self.out_dir = self.root / "out"
        self.project = make_ref_project(
            self.root, (("Groom", "Character"), ("Reporter", "Character"),
                        ("Hall-View-From-Entrance", "Room")))

        self.metadata = {"scenes": [{
            "scene_id": 1,
            "panels": [{
                "panel_index": 1,
                "duration": 4,
                "references": ["Groom", "Reporter"],
                "location_references": ["Hall-View-From-Entrance"],
                "state": {"actors": [
                    {"name": "Groom", "visual_ref": "Groom", "in_frame": True,
                     "pose": "standing", "position": "top step", "gaze_target": "Reporter"}]},
                "motion_intent": "The Groom waits.",
                "motion_prompt": "He straightens his collar.",
                "visual_start": "[SCALE] MS 35mm eye-level cam@[doors]\nactor line\nLIGHT: key left, hard, warm",
                "visual_end": "second image",
                "lights_and_camera": "handheld eye-level",
                "dialogue": "Groom: You came.",
                "voiceover": "",
                "is_reversed": False,
            }],
        }]}
        self.metadata_path = self.root / "animation_metadata.json"
        self.metadata_path.write_text(json.dumps(self.metadata))

        # Panel stills.
        self.static_png = self.panels_dir / "001_01_static.png"
        self.panels_dir.mkdir(exist_ok=True, parents=True)
        self.static_png.write_bytes(b"PNGstatic")
        self.llm = StubLLM()

    def tearDown(self):
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def animator(self, **kw):
        return GrokOpenRouterAnimator(api_key="test", llm=self.llm, project=self.project, **kw)


class DryRunTests(Harness):
    def test_dry_writes_one_dump_and_calls_nothing(self):
        manual_mod._OUTPUT_DIR = self.root / "manual_llm"

        # Item 7b: acting data flows from ref JSONs
        self.project.character_info["Groom"].update({
            "behavioral_signature": "Under pressure: goes quiet. However, when "
                                    "mocked — the jaw tightens and he steps closer.",
            "physical_vocabulary": "Named gait: slow deliberate stride. "
                                   "Softening target: shuffled slippers at home.",
        })
        os.environ["DRY"] = "1"
        self.animator().run_all(self.metadata_path, self.panels_dir, self.out_dir)
        dumps = list((self.root / "manual_llm").glob("*.md"))
        self.assertEqual(len(dumps), 1)
        text = dumps[0].read_text()
        self.assertIn("## PROMPT\n", text)
        self.assertIn("# PAYLOAD\n", text)
        self.assertIn("SCENE CONTEXT", text)  # structured builder, not raw interpolation
        # Item 5b (OpenRouter route): dialogue resolves to a prose voice
        # descriptor bound to the speaker's character <IMAGE_N>.
        self.assertIn("Voice: Groom:", text)
        self.assertIn("<IMAGE_2> (Groom)", text)  # fixture: hall=1, Groom=2
        # Item 7b: ACTING block with the ref-side acting data + EYE LIFE
        self.assertIn("Groom (<IMAGE_2>)", text)
        self.assertIn("Named gait: slow deliberate stride", text)
        self.assertIn("EYE LIFE", text)
        # Item 8a: no anchor_points in the fixture refs -> no GEOMETRY line.
        self.assertNotIn("GEOMETRY", text)
        self.assertEqual(self.llm.calls, [])

    def test_dry_includes_spatial_map_from_anchor_json(self):
        manual_mod._OUTPUT_DIR = self.root / "manual_llm"

        # Item 8a: hall ref gains anchor_points; panel gains a disposition.
        hall = self.project.character_info["Hall-View-From-Entrance"]
        hall["anchor_points"] = {
            "axes": "X: 0=image-left (West), 1=image-right (East). "
                    "View-From-Entrance (camera faces North): depth=Y.",
            "objects": [{"id": "doors", "label": "double doors"},
                        {"id": "top-step", "label": "landing"}],
        }
        self.metadata["scenes"][0]["panels"][0]["visual_disposition"] = \
            "Groom stands on [top-step] behind [doors]"
        self.metadata_path.write_text(json.dumps(self.metadata))

        os.environ["DRY"] = "1"
        self.animator().run_all(self.metadata_path, self.panels_dir, self.out_dir)
        dumps = list((self.root / "manual_llm").glob("*.md"))
        text = dumps[0].read_text()
        block = text.split("SPATIAL BLOCKING:")[1].split("OPTICS:")[0]
        self.assertIn("GEOMETRY — camera side (view Hall-View-From-Entrance)",
                      block)
        self.assertIn("[doors]", block)      # landmark list + disposition
        # One disposition line per SENTENCE, keyed by every anchor it
        # introduces (not one line per anchor repeating the whole prose).
        self.assertIn("[top-step], [doors] — Groom stands on [top-step] "
                      "behind [doors]", block)
        self.assertTrue(block.strip().splitlines()[0].startswith("GEOMETRY"))

    def test_dry_payload_has_ordered_refs_and_baseline_frames(self):
        import base64
        manual_mod._OUTPUT_DIR = self.root / "manual_llm"
        os.environ["DRY"] = "1"
        self.animator().run_all(self.metadata_path, self.panels_dir, self.out_dir)
        text = next((self.root / "manual_llm").glob("*.md")).read_text()
        start = text.index("# PAYLOAD\n") + len("# PAYLOAD\n")
        payload = json.loads(text[start:]) if not text[start:].rstrip().endswith("}") \
            else json.loads(text[start:text.rindex("}") + 1])
        self.assertEqual(payload["duration"], 4)
        # Refs-only transport (probe 3): no frame_images; start frame is
        # input_references[0] binding <IMAGE_0>, ordered refs follow.
        self.assertNotIn("frame_images", payload)
        self.assertEqual(len(payload["input_references"]), 3)
        self.assertEqual(
            base64.b64decode(payload["input_references"][0]["image_url"]["url"].split(",", 1)[1]),
            (self.panels_dir / "001_01_static.png").read_bytes())
        self.assertEqual(
            base64.b64decode(payload["input_references"][1]["image_url"]["url"].split(",", 1)[1]),
            (self.ref_dir / "hall-view-from-entrance.png").read_bytes())
        self.assertNotIn("last_frame", json.dumps(payload))


class WireUpTests(Harness):
    def test_real_prompt_uses_builder_and_passes_refs(self):
        self.animator().run_all(self.metadata_path, self.panels_dir, self.out_dir)
        self.assertEqual(len(self.llm.calls), 1)
        call = self.llm.calls[0]
        self.assertIn("SCENE CONTEXT", call["prompt"])
        self.assertEqual(call["duration"], 4)
        self.assertEqual(len(call["reference_images"]), 2)
        self.assertIsInstance(call["start_image"], Path)
        self.assertIsNone(call["last_frame"])
        self.assertTrue((self.out_dir / "clip_01_001.mp4").exists())

    def test_duration_clamped_to_model_range(self):
        # Our transport is refs-only. The default model,
        # grok-imagine-video-1.5, allows 15 s in reference mode (vendor
        # doc); the older grok-imagine-video allows 10 s (MEASURED
        # 2026-11-12: an 11 s request with input_references returns HTTP
        # 400 "Duration 11s exceeds the maximum allowed for
        # reference-to-video, which is 10s.").
        self.metadata["scenes"][0]["panels"][0]["duration"] = 22
        self.metadata_path.write_text(json.dumps(self.metadata))
        self.animator().run_all(self.metadata_path, self.panels_dir, self.out_dir)
        self.assertEqual(self.llm.calls[0]["duration"], 15)

    def test_duration_within_range_is_untouched(self):
        self.metadata["scenes"][0]["panels"][0]["duration"] = 7
        self.metadata_path.write_text(json.dumps(self.metadata))
        self.animator().run_all(self.metadata_path, self.panels_dir, self.out_dir)
        self.assertEqual(self.llm.calls[0]["duration"], 7)

    def test_end_frame_env_warns_and_disables_probe2_rejected(self):
        # Probe 2 (2026-11-10): OpenRouter 400 "the provider integration for
        # model x-ai/grok-imagine-video-1.5 does not support last_frame
        # frame_images". The env flag must not produce a payload that dies.
        import logging
        (self.panels_dir / "001_01_end.png").write_bytes(b"PNGend")
        os.environ["AI_OPENROUTER_LAST_FRAME"] = "1"
        with self.assertLogs(level=logging.WARNING):
            self.animator().run_all(self.metadata_path, self.panels_dir, self.out_dir)
        self.assertIsNone(self.llm.calls[0]["last_frame"])

    def test_end_frame_default_off(self):
        (self.panels_dir / "001_01_end.png").write_bytes(b"PNGend")
        self.animator().run_all(self.metadata_path, self.panels_dir, self.out_dir)
        self.assertIsNone(self.llm.calls[0]["last_frame"])

    def test_reversed_panel_skips_pin_until_probe(self):
        (self.panels_dir / "001_01_end.png").write_bytes(b"PNGend")
        self.metadata["scenes"][0]["panels"][0]["is_reversed"] = True
        self.metadata_path.write_text(json.dumps(self.metadata))
        os.environ["AI_OPENROUTER_LAST_FRAME"] = "1"
        self.animator().run_all(self.metadata_path, self.panels_dir, self.out_dir)
        self.assertIsNone(self.llm.calls[0]["last_frame"])


class FailingLLM(StubLLM):
    def generate_video(self, **kwargs):
        raise RuntimeError("provider exploded")


class FatalLLM(StubLLM):
    def generate_video(self, **kwargs):
        raise SystemExit(2)


class FailureTests(Harness):
    def test_run_all_raises_when_a_clip_fails(self):
        self.llm = FailingLLM()
        with self.assertRaises(RuntimeError) as ctx:
            self.animator().run_all(self.metadata_path, self.panels_dir,
                                    self.out_dir)
        self.assertIn("1/1", str(ctx.exception))

    def test_run_all_does_not_swallow_system_exit(self):
        self.llm = FatalLLM()
        with self.assertRaises(SystemExit):
            self.animator().run_all(self.metadata_path, self.panels_dir,
                                    self.out_dir)


    def test_fatal_error_cancels_queued_clips(self):
        panel = self.metadata["scenes"][0]["panels"][0]
        self.metadata["scenes"][0]["panels"] = [
            {**panel, "panel_index": i} for i in (1, 2, 3)]
        self.metadata_path.write_text(json.dumps(self.metadata))
        for i in (2, 3):
            (self.panels_dir / f"001_0{i}_static.png").write_bytes(b"PNG")
        calls = []

        class CountingFatal(StubLLM):
            def generate_video(self, **kwargs):
                calls.append(kwargs)
                raise SystemExit(2)

        self.llm = CountingFatal()
        with self.assertRaises(SystemExit):
            self.animator(batch_size=1).run_all(
                self.metadata_path, self.panels_dir, self.out_dir)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
