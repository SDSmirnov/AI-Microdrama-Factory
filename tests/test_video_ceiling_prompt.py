"""The video-clip ceiling reaches the screenwriter prompts from ONE source.

The prompts used to hard-code 6 s in three places ("MOTION BUDGET — 6
seconds is real time", "the ~6s clip", "animated in ~6s clips") while the
transport enforced a different limit. A number in prose and a number in
code drift, and the symptom is an HTTP 400 mid-batch rather than a clamp.

The mechanism: lib/core/prompts.py substitutes `{{VIDEO_MAX_SECONDS}}` when
it loads a prompt file, using the model's own reference-mode cap from
lib/animation/capabilities.py.

The cap is PER MODEL:
    grok-imagine-video-1.5   15 s (vendor doc)
    grok-imagine-video      10 s (MEASURED: an 11 s request with
                             input_references returns HTTP 400 "Duration 11s
                             exceeds the maximum allowed for
                             reference-to-video, which is 10s.")
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.core import prompts as prompts_mod


class SubstitutionTests(unittest.TestCase):
    def setUp(self):
        self._model = os.environ.get("AI_VIDEO_MODEL")
        os.environ.pop("AI_VIDEO_MODEL", None)

    def tearDown(self):
        os.environ.pop("AI_VIDEO_MODEL", None)
        if self._model is not None:
            os.environ["AI_VIDEO_MODEL"] = self._model

    def test_placeholder_is_replaced(self):
        out = prompts_mod._substitute("clip up to {{VIDEO_MAX_SECONDS}} s")
        self.assertNotIn("{{VIDEO_MAX_SECONDS}}", out)
        self.assertIn("15 s", out)

    def test_target_language_still_substituted(self):
        out = prompts_mod._substitute("say it in {target_language}")
        self.assertIn(prompts_mod.TARGET_LANGUAGE, out)
        self.assertNotIn("{target_language}", out)

    def test_ceiling_follows_the_configured_model(self):
        os.environ["AI_VIDEO_MODEL"] = "x-ai/grok-imagine-video"
        out = prompts_mod._substitute("{{VIDEO_MAX_SECONDS}}")
        self.assertIn("10", out)
        os.environ["AI_VIDEO_MODEL"] = "x-ai/grok-imagine-video-1.5"
        out = prompts_mod._substitute("{{VIDEO_MAX_SECONDS}}")
        self.assertIn("15", out)


class PromptFileTests(unittest.TestCase):
    """The prompt files must not carry their own copy of the limit."""

    PROMPT_DIR = Path(__file__).resolve().parents[1] / "lib" / "prompting"

    def _files(self):
        for style in sorted(self.PROMPT_DIR.iterdir()):
            if not style.is_dir():
                continue
            for md in sorted(style.glob("*.md")):
                yield style.name, md

    def test_no_prompt_file_asserts_a_fixed_clip_length(self):
        """The old prose said "6 seconds is real time" / "the ~6s clip" /
        "animated in ~6s clips" - these assert the CLIP's length, and they
        contradict a model that can run longer.

        A per-hook-type duration ("duration 6s" for the confrontation beat)
        is a DRAMATURGICAL default, not a transport limit - it is allowed,
        and the ceiling bounds it.
        """
        asserting = ("6 seconds is real time",
                     "the ~6s clip",
                     "animated in ~6s clips",
                     "(always — hard cap)")
        stale = []
        for style, md in self._files():
            text = md.read_text(encoding="utf-8")
            for phrase in asserting:
                if phrase in text:
                    stale.append(f"{style}/{md.name}: {phrase!r}")
        self.assertEqual(stale, [], "prompt files still assert a fixed clip length")

    def test_hook_durations_stay_within_the_ceiling(self):
        """No per-hook duration may exceed the model's reference-mode cap,
        or the panel would be planned longer than the model accepts."""
        from lib.animation.capabilities import caps_for
        cap = caps_for(os.getenv("AI_VIDEO_MODEL",
                                 "x-ai/grok-imagine-video-1.5")).ref_max_seconds
        import re
        offenders = []
        for style, md in self._files():
            for m in re.finditer(r"duration[:\s]+(\d+)[–-](\d+)?\s*s",
                                 md.read_text(encoding="utf-8")):
                hi = int(m.group(2) or m.group(1))
                if hi > cap:
                    offenders.append(f"{style}/{md.name}: {m.group(0)}")
        self.assertEqual(offenders, [],
                         f"hook durations above the {cap}s model cap")

    def test_every_placeholder_is_in_a_prompt_file_that_gets_substituted(self):
        """A placeholder in a file that is never loaded would reach the
        model literally."""
        for style, md in self._files():
            if "{{VIDEO_MAX_SECONDS}}" not in md.read_text(encoding="utf-8"):
                continue
            stem = md.name.split(".")[0]   # pass2_visual.patch.md edits pass2_visual
            self.assertIn(stem, prompts_mod.prompt_names(style),
                          f"{style}/{md.name} carries the placeholder but is not "
                          "a loaded prompt, so it would never be substituted")

    def test_multishot_guidance_is_in_pass2_not_pass3(self):
        """PASS2 fills in each shot's description and camera. PASS3 must not
        emit `shots`: the passes merge p1 -> p1a -> p2 -> p3 with later
        wins, so a PASS3 `shots` would replace PASS2's descriptions."""
        for style in sorted(self.PROMPT_DIR.iterdir()):
            if not style.is_dir():
                continue
            p2 = style / "pass2_visual.md"
            p3 = style / "pass3_motion_audio.md"
            if p2.exists():
                self.assertIn("MULTI-SHOT", p2.read_text(encoding="utf-8"),
                              f"{style.name}/pass2_visual.md")
            if p3.exists():
                self.assertNotIn('"shots"', p3.read_text(encoding="utf-8"),
                                 f"{style.name}/pass3_motion_audio.md must not "
                                 "ask for a `shots` array")


class SingleSourceTests(unittest.TestCase):
    """The video model must be read the same way everywhere.

    Three call sites consult it: the prompt substitution, the OpenRouter
    client, and the animator. If they disagree, the screenwriter plans
    panels for one model and the animator sends them to another.
    """

    def setUp(self):
        self._model = os.environ.get("AI_VIDEO_MODEL")
        os.environ.pop("AI_VIDEO_MODEL", None)

    def tearDown(self):
        os.environ.pop("AI_VIDEO_MODEL", None)
        if self._model is not None:
            os.environ["AI_VIDEO_MODEL"] = self._model

    def test_all_call_sites_agree(self):
        from lib.animation.capabilities import default_video_model
        from lib.animation.grok_openrouter import GrokOpenRouterAnimator
        from lib.llm.openrouter import OpenRouterLLM

        os.environ["AI_VIDEO_MODEL"] = "x-ai/grok-imagine-video"
        expected = "x-ai/grok-imagine-video"
        self.assertEqual(default_video_model(), expected)
        self.assertEqual(
            OpenRouterLLM(api_key="x", text_model="t", image_model="").video_model,
            expected)
        self.assertEqual(GrokOpenRouterAnimator(api_key="x").model, expected)

    def test_the_model_is_read_at_call_time(self):
        """A value frozen at import time would silently disagree with the
        animator if AI_VIDEO_MODEL is set after the import."""
        from lib.animation.capabilities import default_video_model
        self.assertEqual(default_video_model(),
                         "x-ai/grok-imagine-video-1.5")
        os.environ["AI_VIDEO_MODEL"] = "x-ai/grok-imagine-video"
        self.assertEqual(default_video_model(), "x-ai/grok-imagine-video")


class PassOwnershipTests(unittest.TestCase):
    def test_pass2_owns_shots(self):
        from lib.core.schemas import PASS2_SCHEMA, PASS3_SCHEMA
        p2 = PASS2_SCHEMA["properties"]["panels"]["items"]["properties"]
        p3 = PASS3_SCHEMA["properties"]["panels"]["items"]["properties"]
        self.assertIn("shots", p2)
        self.assertNotIn("shots", p3)

    def test_pass1_schema_cannot_carry_shots(self):
        from lib.core.schemas import PASS1_SCHEMA
        panels = PASS1_SCHEMA["properties"]["scenes"]["items"]["properties"][
            "panels"]["items"]
        self.assertNotIn("shots", panels["properties"])
        self.assertFalse(panels.get("additionalProperties", True))


if __name__ == "__main__":
    unittest.main()
