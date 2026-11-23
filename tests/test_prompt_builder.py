"""Unit tests for the structured video prompt builder (Item 3, GROK-VIDEO-PLAN).

build_video_prompt(panel, refs, voices, duration) -> str:
nine fixed blocks in fixed order; references bound to RefBite tags; positive
locks plus the hard prohibition text (restored 2026-11-11 on real-clip
evidence); no hardcoded genre/lens; legacy prose visual_start builds too
(no OPTICS).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.animation.refs import RefBite
from lib.animation.prompt_builder import (
    POSITIVE_PHOTO_LOCKS, VoiceBite, build_video_prompt,
)


def _bites():
    return [
        RefBite("<IMAGE_0>", None, "first_frame", "001_01_static", ""),
        RefBite("<IMAGE_1>", None, "location", "Mansion-Hall-View-From-Entrance",
                "Mansion hall seen from the doors."),
        RefBite("<IMAGE_2>", None, "character", "Groom",
                "Groom in black tuxedo. — pose: standing, position: top step, gaze: Reporter"),
    ]


def _panel(vs=None, dialogue="", voiceover="", sound_design="crowd murmur and shutter clicks",
           anchor_refs=None):
    vs = vs or (
        "[SCALE] MS 35mm eye-level cam@[courtyard-center]\n"
        "REP: frame-CENTER FG, FRONTAL->gaze:[main-doors], chest->[mansion], standing, mic raised 10 cm\n"
        "BG: [main-doors], columns sharp, stretcher soft\n"
        "BGD: sparse guests, MG, heavy-bokeh\n"
        "LIGHT: key from left, hard, warm(3200 K), fill 1:4\n"
        'PROP: [wedding-bouquet] in her left hand, held\n'
        "CONTEXT: cold wind off the lawn"
    )
    return {
        "panel_index": 1,
        "motion_intent": "The Reporter establishes the significance of the wedding.",
        "motion_prompt": "She lowers the mic 5 cm and steps half-left.",
        "visual_start": vs,
        "visual_disposition": "Reporter at courtyard-center facing the mansion.",
        "anchor_refs": anchor_refs if anchor_refs is not None else [],
        "dialogue": dialogue,
        "voiceover": voiceover,
        "voiceover_settings": {"gender": "female", "actor": "", "age": "", "tone": ""},
        "sound_design": sound_design,
        "duration": 6,
    }


class BlockOrderTests(unittest.TestCase):
    def test_ten_blocks_in_fixed_order(self):
        prompt = build_video_prompt(_panel(), _bites(), [], 6)
        order = ["SCENE CONTEXT", "ACTIVE REFERENCES", "SPATIAL BLOCKING", "OPTICS",
                 "CAMERA", "ACTION TIMING", "LIGHTING", "AUDIO", "POSITIVE LOCKS",
                 "HARD PROHIBITIONS"]
        pos = [prompt.find(f"{b}:") for b in order]
        self.assertTrue(all(p >= 0 for p in pos), f"missing blocks: {pos}")
        self.assertEqual(pos, sorted(pos))

    def test_scene_context_uses_motion_intent(self):
        prompt = build_video_prompt(_panel(), _bites(), [], 6)
        self.assertIn("The Reporter establishes the significance of the wedding.", prompt)


class ReferenceBindingTests(unittest.TestCase):
    def test_active_references_lists_every_bite(self):
        prompt = build_video_prompt(_panel(), _bites(), [], 6)
        self.assertIn("<IMAGE_0>", prompt)
        # Probe 3b (2026-11-10): input_references[0] is guidance, not a pinned
        # frame — the prompt must not claim frame-exact ground truth.
        self.assertNotIn("ground truth", prompt)
        self.assertIn("approximate its framing", prompt)
        self.assertIn("<IMAGE_1> (Mansion-Hall-View-From-Entrance", prompt)
        self.assertIn("<IMAGE_2> (Groom", prompt)
        self.assertIn("Groom in black tuxedo", prompt)
        self.assertIn("matches the reference", prompt)

    def test_disposition_and_anchors_in_spatial_blocking(self):
        prompt = build_video_prompt(_panel(), _bites(), [], 6,
                                   anchor_refs=["stairs", "main-doors"])
        self.assertIn("Reporter at courtyard-center facing the mansion.", prompt)
        self.assertIn("stairs", prompt.split("SPATIAL BLOCKING:")[1].split("OPTICS:")[0])

    def test_light_and_bgd_lines_live_in_lighting_not_spatial(self):
        prompt = build_video_prompt(_panel(), _bites(), [], 6)
        spatial = prompt.split("SPATIAL BLOCKING:")[1].split("OPTICS:")[0]
        lighting = prompt.split("LIGHTING:")[1].split("AUDIO:")[0]
        self.assertIn("LIGHT: key from left", lighting)
        self.assertIn("BGD: sparse guests", lighting)
        self.assertNotIn("LIGHT: key from left", spatial)
        self.assertNotIn("BGD: sparse guests", spatial)


class OpticsTests(unittest.TestCase):
    def test_lens_translated_to_fov_with_outcome(self):
        for lens, fov in (("35", "63"), ("50", "47"), ("24", "84"), ("85", "29")):
            prompt = build_video_prompt(_panel(vs=_panel()["visual_start"].replace("35mm", f"{lens}mm")),
                                        _bites(), [], 6)
            self.assertIn(f"{fov}°", prompt)
        prompt = build_video_prompt(_panel(), _bites(), [], 6)
        self.assertIn("One lens for the entire shot", prompt)

    def test_header_without_scale_bracket_literal(self):
        # Generated metadata writes 'CU 50mm high-angle cam@anchor' (no [SCALE] token).
        legacy = ("CU 50mm high-angle cam@[fold-out-metal-desk]\n"
                  "Chen-Dajie: frame-center FG, seated.")
        prompt = build_video_prompt(_panel(vs=legacy), _bites(), [], 6)
        optics = prompt.split("OPTICS:")[1].split("CAMERA:")[0]
        self.assertIn("47°", optics)
        self.assertIn("close-up", optics)
        self.assertIn("high-angle", optics)

    def test_legacy_prose_falls_back_without_lens_numbers(self):
        legacy = ("Medium shot. The Reporter stands center-frame holding a mic. "
                  "Behind her the couple on the stairs.")
        prompt = build_video_prompt(_panel(vs=legacy), _bites(), [], 6)
        optics = prompt.split("OPTICS:")[1].split("CAMERA:")[0]
        self.assertIn("no lens data", optics)
        self.assertNotIn("mm", optics)  # nothing invented for legacy prose

    def test_legacy_prose_builds_all_other_blocks(self):
        legacy = "Medium shot. The Reporter stands center-frame holding a mic."
        prompt = build_video_prompt(_panel(vs=legacy), _bites(), [], 6)
        self.assertIn("SPATIAL BLOCKING:", prompt)
        self.assertIn("CAMERA:", prompt)


class AudioTests(unittest.TestCase):
    def test_dialogue_lines_and_silence_rules(self):
        prompt = build_video_prompt(_panel(dialogue="Reporter: This is the wedding of the year!"),
                                    _bites(), [], 6)
        audio = prompt.split("AUDIO:")[1].split("POSITIVE LOCKS:")[0]
        self.assertIn("Reporter: This is the wedding of the year!", audio)
        self.assertIn("SFX only", prompt)
        self.assertIn("No music", prompt)
        self.assertIn("1 second of silence", prompt)
        self.assertIn("no ad-libs in any language", prompt)

    def test_voiceover_says_lips_do_not_move(self):
        prompt = build_video_prompt(_panel(voiceover="Just play your part."),
                                    _bites(), [], 6)
        self.assertIn("lips do not move", prompt)
        self.assertIn("Just play your part.", prompt)

    def test_speaker_count_lock(self):
        prompt = build_video_prompt(_panel(dialogue="Reporter: Hello.\nGroom: Hi."),
                                    _bites(), [], 6)
        self.assertIn("Exactly 2", prompt)

    def test_voice_tags_bound_to_speakers(self):
        voices = [VoiceBite("<AUDIO_0>", "Groom", "You came.", "dialogue")]
        prompt = build_video_prompt(_panel(dialogue="Groom: You came."), _bites(), voices, 6)
        self.assertIn("<AUDIO_0>", prompt)
        self.assertIn("Groom", prompt.split("AUDIO:")[1])

    def test_no_dialogue_no_speaker_lock(self):
        prompt = build_video_prompt(_panel(dialogue="", voiceover=""), _bites(), [], 6)
        self.assertNotIn("Exactly", prompt)


class PositiveLocksTests(unittest.TestCase):
    def test_location_bite_gets_framing_ban(self):
        prompt = build_video_prompt(_panel(), _bites(), [], 6)
        self.assertIn("Mansion-Hall-View-From-Entrance", prompt.split("POSITIVE LOCKS:")[1])
        self.assertIn("geometry", prompt.split("POSITIVE LOCKS:")[1])
        self.assertIn("not framing", prompt.split("POSITIVE LOCKS:")[1])

    def test_photo_locks_always_present_and_positive_constant_reused(self):
        prompt = build_video_prompt(_panel(), _bites(), [], 6)
        self.assertIn(POSITIVE_PHOTO_LOCKS, prompt)

    def test_removed_legacy_text_stays_out(self):
        prompt = build_video_prompt(_panel(), _bites(), [], 6)
        self.assertNotIn("Filming Action Movie", prompt)
        self.assertNotIn("Arri Alexa", prompt)
        self.assertNotIn("ANIMATION_PROHIBITIONS", prompt)


class HardProhibitionsTests(unittest.TestCase):
    """User evidence (2026-11-11, real clips): positive-phrasing locks alone
    do not stop Grok's exaggeration drift — tears, breath vapor, theatrical
    facial extremes still appear. The hard prohibition text (ANIMATION_
    PROHIBITIONS content) is therefore restored as its own block."""

    def test_prohibition_content_present_in_prompt(self):
        prompt = build_video_prompt(_panel(), _bites(), [], 6)
        for phrase in ("CRITICALLY FORBIDDEN", "NO tears", "NO breath vapor",
                       "no bared teeth", "NO sweat"):
            self.assertIn(phrase, prompt)

    def test_prohibition_block_is_last(self):
        prompt = build_video_prompt(_panel(), _bites(), [], 6)
        blocks = prompt.split("\n\n")
        self.assertTrue(blocks[-1].startswith("HARD PROHIBITIONS:"))
        self.assertIn("CRITICALLY FORBIDDEN", blocks[-1])

    def test_prohibitions_single_source_of_truth_with_base(self):
        from lib.animation.base import ANIMATION_PROHIBITIONS
        from lib.animation.prompt_builder import _hard_prohibitions
        self.assertEqual(_hard_prohibitions(), ANIMATION_PROHIBITIONS)


class ActionTimingTests(unittest.TestCase):
    def test_motion_prompt_verbatim_and_duration_framed(self):
        prompt = build_video_prompt(_panel(), _bites(), [], 6)
        self.assertIn("She lowers the mic 5 cm and steps half-left.", prompt)
        self.assertIn("6", prompt.split("ACTION TIMING:")[1].split("LIGHTING:")[0])


class SpeakerNameTests(unittest.TestCase):
    def test_yo_and_ye_spellings_match(self):
        from lib.animation.prompt_builder import _norm_name
        self.assertEqual(_norm_name("Пётр"), _norm_name("Петр"))
        self.assertEqual(_norm_name("Anna-Maria"), "annamaria")


if __name__ == "__main__":
    unittest.main()
