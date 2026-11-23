"""Item 9: identity stress test (stress-refs).

Command `stress-refs NAME [--gens N]` (default 5). Action bank is neutral
(no weapon/safety-trigger terms), cycled to N. Each generation uses the
character ref(s) + the character's default location ref via the Item 2
assembler and the Item 3 builder; output
cinematic_render/stress_tests/{name}_{NN}.mp4 + one jsonl report line
(prompt hash, action, clip path) — a report, not a second source of
truth. Pass criterion: recognizable as the same person across all N
generations while in action, judged via the vision-QA path with a
logged human-review fallback.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.animation.grok_openrouter import GrokOpenRouterAnimator, STRESS_ACTIONS
from lib.llm import manual as manual_mod

from support import StubLLM, make_ref_project


class StubVisionLLM:
    def __init__(self, verdict=None, error=None):
        self.calls = []
        self._verdict = verdict if verdict is not None else {
            "identity_same": True, "note": "same face"}
        self._error = error

    def analyze_video(self, video, prompt, schema):
        if self._error:
            raise self._error
        self.calls.append(video)
        return self._verdict


def _make_env(root):
    return make_ref_project(
        root, (("Private-Hu", "Character"),
               ("Observation-Post-View-Primary", "Room")), desc="view.")


METADATA = {"scenes": [{
    "scene_id": 1,
    "panels": [
        {"panel_index": 1, "location_references": ["Observation-Post-View-Primary"],
         "state": {"actors": [{"name": "Private-Hu", "visual_ref": "Private-Hu",
                               "in_frame": True}]}},
        {"panel_index": 2, "location_references": ["Observation-Post-View-Primary"],
         "state": {"actors": [{"name": "Private-Hu", "visual_ref": "Private-Hu",
                               "in_frame": True}]}},
        {"panel_index": 3, "location_references": ["Other-Place"],
         "state": {"actors": []}},
    ]}]}


class StressRefsTests(unittest.TestCase):
    def setUp(self):
        self._env = {k: os.environ.pop(k, None) for k in ("DRY",)}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_manual_dir = manual_mod._OUTPUT_DIR
        self.addCleanup(setattr, manual_mod, '_OUTPUT_DIR', self._orig_manual_dir)
        self.root = Path(self.tmp.name)
        self.project = _make_env(self.root)
        self.out_dir = self.root / "stress_tests"
        self.llm = StubLLM()

    def tearDown(self):
        for k, v in self._env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def animator(self):
        return GrokOpenRouterAnimator(api_key="test", llm=self.llm,
                                      project=self.project)

    def test_default_five_gens_from_action_bank(self):
        self.animator().stress_refs("Private-Hu", None, self.out_dir,
                                    metadata=METADATA)
        self.assertEqual(len(self.llm.calls), len(STRESS_ACTIONS[:5]))
        clips = sorted(self.out_dir.glob("private-hu_*.mp4"))
        self.assertEqual(len(clips), 5)
        lines = (self.out_dir / "report.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 5)
        rec = json.loads(lines[0])
        for key in ("name", "gen", "action", "prompt_hash", "clip"):
            self.assertIn(key, rec)
        self.assertEqual(rec["gen"], 1)

    def test_actions_cycled_neutral_and_bound_to_prompt(self):
        self.animator().stress_refs("Private-Hu", 2, self.out_dir,
                                    metadata=METADATA)
        prompts = [c["prompt"] for c in self.llm.calls]
        self.assertIn(STRESS_ACTIONS[0].lower(), prompts[0].lower())
        self.assertIn(STRESS_ACTIONS[1].lower(), prompts[1].lower())
        for p in prompts:  # neutral bank: no safety-trigger vocabulary
            for bad in ("weapon", "rifle", "gun", "blood"):
                self.assertNotIn(bad, p.lower())

    def test_character_start_image_plus_default_location_ref(self):
        self.animator().stress_refs("Private-Hu", 1, self.out_dir,
                                    metadata=METADATA)
        call = self.llm.calls[0]
        # start image = the character's primary ref PNG (identity anchor)
        self.assertTrue(str(call["start_image"]).endswith("private-hu.png"))
        refs = [Path(p).name for p in call["reference_images"]]
        self.assertIn("observation-post-view-primary.png", refs)

    def test_default_location_is_characters_most_common(self):
        self.animator().stress_refs("Private-Hu", 1, self.out_dir,
                                    metadata=METADATA)
        # Observation-Post appears in 2 of Private-Hu's panels vs Other 0.
        refs = [Path(p).name for p in self.llm.calls[0]["reference_images"]]
        self.assertIn("observation-post-view-primary.png", refs)
        self.assertNotIn("other-place.png", refs)

    def test_no_metadata_skips_location_with_log(self):
        import logging
        with self.assertLogs(level=logging.INFO) as logs:
            self.animator().stress_refs("Private-Hu", 1, self.out_dir,
                                        metadata=None)
        refs = [Path(p).name for p in self.llm.calls[0]["reference_images"]]
        self.assertEqual(refs, [])
        self.assertTrue(any("location" in o.lower() for o in logs.output))

    def test_dry_dumps_instead_of_submitting(self):
        os.environ["DRY"] = "1"
        manual_mod._OUTPUT_DIR = self.root / "manual_llm"
        out = self.animator().stress_refs("Private-Hu", None, self.out_dir,
                                          metadata=METADATA)
        self.assertIsNone(out)
        self.assertEqual(self.llm.calls, [])
        self.assertEqual(len(list((self.root / "manual_llm").glob(
            "stress_private-hu_*.md"))), 5)

    def test_judge_appends_identity_verdict_to_report(self):
        self.animator().stress_refs("Private-Hu", 2, self.out_dir,
                                    metadata=METADATA)
        vision = StubVisionLLM()
        self.animator().judge_stress("Private-Hu", self.out_dir,
                                     vision_llm=vision)
        lines = [json.loads(l)
                 for l in (self.out_dir / "report.jsonl").read_text().splitlines()]
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(r.get("identity_same") is True for r in lines))
        self.assertEqual(len(vision.calls), 2)

    def test_judge_fallback_on_unsupported_backend(self):
        import logging
        self.animator().stress_refs("Private-Hu", 1, self.out_dir,
                                    metadata=METADATA)

        class NoVideo:
            def analyze_video(self, video, prompt, schema):
                raise NotImplementedError("no video")

        with self.assertLogs(level=logging.WARNING) as logs:
            self.animator().judge_stress("Private-Hu", self.out_dir,
                                         vision_llm=NoVideo())
        self.assertTrue(any("human review" in o.lower()
                            for o in logs.output))


if __name__ == "__main__":
    unittest.main()
