"""Model-selection defaults: pinned off the Google deprecation cliff.

Google AI Studio deprecations (fetched 2026-11-12):
  gemini-2.5-pro    -> 2026-12-01 auto-routes to gemini-3.8-flash
  gemini-2.5-flash  -> 2026-12-01 auto-routes to gemini-3.5-flash-lite
  gemini-2.5-flash-preview-tts -> SHUT DOWN 2026-11-18
  gemini-3-pro-image-preview / gemini-3.1-flash-image-preview
                    -> shut down 2026-06-25
  gemini-3.5-flash  -> auto-routes to gemini-3.6-flash
  gemini-3.7-flash  -> auto-routes to gemini-3.8-flash

A default that silently changes model mid-production is a production bug, so
these are pinned and asserted here.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.core.project import Project

# Ids Google auto-routes or shuts down. Anything in this set is a silent
# behaviour change waiting to happen.
DEPRECATED_OR_ROUTING = {
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash-preview",
    "gemini-3-pro-image-preview",
    "gemini-3.1-flash-image-preview",
    "gemini-2.5-flash-image-preview",
    "gemini-3.5-flash",
    "gemini-3.7-flash",
    "gemini-3.1-flash-lite-preview",
    "gemini-3-pro-image",
    "gemini-2.5-flash-preview-tts",
}


class ModelDefaultTests(unittest.TestCase):
    ENV_VARS = ("AI_TEXT_MODEL", "AI_QA_MODEL", "AI_IMAGE_MODEL", "AI_GEMINI_MODEL")

    def setUp(self):
        self._orig_env = {var: os.environ.get(var) for var in self.ENV_VARS}
        for var in self.ENV_VARS:
            os.environ.pop(var, None)
        self.p = Project()

    def tearDown(self):
        for var, value in self._orig_env.items():
            if value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = value

    def test_defaults_are_not_on_the_deprecation_cliff(self):
        for name in ("text_model", "qa_model", "image_model", "gemini_model"):
            model = getattr(self.p, name)
            self.assertNotIn(model, DEPRECATED_OR_ROUTING,
                             f"{name} default '{model}' is deprecated or "
                             f"auto-routes to another model")

    def test_qa_model_defaults_to_text_model(self):
        self.assertEqual(self.p.qa_model, self.p.text_model)

    def test_qa_model_overridable_independently(self):
        os.environ["AI_TEXT_MODEL"] = "google/gemini-4-argon"
        os.environ["AI_QA_MODEL"] = "google/gemini-3.8-flash"
        p = Project()
        self.assertEqual(p.text_model, "google/gemini-4-argon")
        self.assertEqual(p.qa_model, "google/gemini-3.8-flash")

    def test_qa_model_falls_back_to_text_model_when_env_empty(self):
        os.environ["AI_TEXT_MODEL"] = "google/gemini-4-argon"
        os.environ["AI_QA_MODEL"] = ""
        p = Project()
        self.assertEqual(p.qa_model, "google/gemini-4-argon")

    def test_vision_llm_uses_qa_model(self):
        from lib.commands.common import _make_vision_llm

        os.environ["AI_QA_MODEL"] = "google/gemini-3.8-flash"
        p = Project()
        p.openrouter_api_key = "sk-test"
        llm = _make_vision_llm("openrouter", p)
        self.assertEqual(llm.text_model, "google/gemini-3.8-flash")

    def test_vision_llm_falls_back_to_text_model(self):
        from lib.commands.common import _make_vision_llm

        p = Project()
        p.openrouter_api_key = "sk-test"
        llm = _make_vision_llm("openrouter", p)
        self.assertEqual(llm.text_model, p.text_model)

    def test_qa_judge_is_flash_with_low_reasoning_and_not_deprecated(self):
        from lib.commands.common import _make_vision_llm
        from lib.core.project import QA_JUDGE_MODEL, QA_REASONING_EFFORT

        self.assertNotIn(QA_JUDGE_MODEL, DEPRECATED_OR_ROUTING)
        self.p.openrouter_api_key = "sk-test"
        llm = _make_vision_llm("openrouter", self.p, model=QA_JUDGE_MODEL,
                               reasoning_effort=QA_REASONING_EFFORT)
        self.assertEqual((llm.text_model, llm.reasoning_effort),
                         ("google/gemini-3.8-flash", "low"))

    def test_reasoning_effort_is_sent_only_when_set(self):
        from unittest import mock
        from lib.llm.openrouter import OpenRouterLLM

        reply = {"choices": [{"message": {"content": "{}"}}]}
        for effort, expected in (("low", {"effort": "low"}), ("", None)):
            llm = OpenRouterLLM(api_key="k", text_model="t", image_model="i")
            llm.reasoning_effort = effort
            with mock.patch.object(llm, "_post_openrouter", return_value=reply) as post:
                llm.analyze_image(image=b"\x89PNG", prompt="judge", schema={"type": "object"})
            self.assertEqual(post.call_args[0][0].get("reasoning"), expected)

    def test_vision_llm_model_override_wins(self):
        from lib.commands.common import _make_vision_llm

        os.environ["AI_QA_MODEL"] = "google/gemini-3.8-flash"
        p = Project()
        p.openrouter_api_key = "sk-test"
        llm = _make_vision_llm(
            "openrouter", p, model="google/gemini-4-hydrogen"
        )
        self.assertEqual(llm.text_model, "google/gemini-4-hydrogen")


if __name__ == "__main__":
    unittest.main()
