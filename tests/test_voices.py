"""Item 5b (OpenRouter route): per-speaker voice resolution.

OpenRouter refs-only has no <AUDIO_N> passthrough (probe 4: field not in the
API surface, allowed_passthrough_parameters=[] on all grok video models), so
resolve_voice() emits PROSE descriptors bound to character image tags
instead of voice slots. VoiceBite.tag stays empty on this route.
"""
import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.animation.prompt_builder import build_video_prompt
from lib.animation.refs import RefBite
from lib.animation.voices import resolve_voice


def _panel(dialogue="Ху (мужской): Опять учения.", settings=None):
    panel = {
        "panel_index": 1,
        "motion_prompt": "He speaks.",
        "dialogue": dialogue,
        "voiceover": "",
        "sound_design": "radio static",
        "visual_start": "MS 35mm eye-level cam@[wall]\nLight: dim",
    }
    if settings is not None:
        panel["voiceover_settings"] = settings
    return panel


def _bites():
    return [
        RefBite("<IMAGE_0>", None, "first_frame", "001_01_static", ""),
        RefBite("<IMAGE_1>", None, "location", "Observation-Post", "a post over a beach"),
        RefBite("<IMAGE_2>", None, "character", "Lin-Wei-ming", "34yo Taiwanese man"),
        RefBite("<IMAGE_3>", None, "character", "Private-Hu", "early-20s conscript"),
    ]


REAL_SETTINGS = {"gender": "male", "actor": "Lin-Wei-ming", "age": "35",
                 "tone": "tired, analytical"}


class ResolveVoiceTests(unittest.TestCase):
    def test_nick_matches_actor_keeps_full_profile(self):
        # 'Линь' -> 'lin' matches Lin-Wei-ming, same character the panel's
        # voiceover_settings.actor names — full profile applies.
        p = _panel(dialogue="Линь (мужской): Три-двенадцать.", settings=REAL_SETTINGS)
        voices = resolve_voice(p, _bites())
        self.assertEqual(len(voices), 1)
        v = voices[0]
        self.assertEqual(v.tag, "")  # no AUDIO slots on the OpenRouter route
        self.assertIn("Линь", v.speaker)
        self.assertIn("male", v.descriptor)
        self.assertIn("35", v.descriptor)
        self.assertIn("tired, analytical", v.descriptor)
        self.assertIn("<IMAGE_2> (Lin-Wei-ming)", v.descriptor)

    def test_mismatched_actor_binds_nick_without_profile(self):
        # Data reality (CRAB metadata): 9/13 dialogue panels carry a
        # voiceover_settings.actor that names a DIFFERENT character than the
        # dialogue speaker. The speaker is who the dialogue prefix names, so
        # nick binding wins and the foreign profile (age/tone) must NOT leak
        # onto the other character's voice.
        voices = resolve_voice(_panel(settings=REAL_SETTINGS), _bites())
        v = voices[0]
        self.assertIn("<IMAGE_3> (Private-Hu)", v.descriptor)  # nick 'Ху'->Hu
        self.assertNotIn("Lin-Wei-ming", v.descriptor)
        self.assertNotIn("35", v.descriptor)
        self.assertNotIn("tired", v.descriptor)
        self.assertIn("male", v.descriptor)  # gender from the line annotation

    def test_missing_settings_falls_back_to_transliteration(self):
        # 'Линь' transliterates to 'lin' -> matches Lin-Wei-ming.
        p = _panel(dialogue="Линь (мужской): Три-двенадцать.", settings=None)
        voices = resolve_voice(p, _bites())
        self.assertEqual(len(voices), 1)
        self.assertIn("<IMAGE_2> (Lin-Wei-ming)", voices[0].descriptor)

    def test_three_speakers_all_get_descriptors(self):
        dialogue = "Ху (мужской): Раз.\nГуо (male): Два.\nЛинь (мужской): Три."
        voices = resolve_voice(_panel(dialogue=dialogue, settings=REAL_SETTINGS), _bites())
        self.assertEqual(len(voices), 3)

    def test_actor_absent_from_bites_drops_profile(self):
        # voiceover_settings.actor names a character that is NOT a bite of
        # this panel (CRAB p05 shape): the profile cannot be verified for the
        # speaking nick, so only the annotation gender is used.
        settings = {"gender": "male", "actor": "Chen-Dajie", "age": "55",
                    "tone": "gruff"}
        p = _panel(dialogue="Линь (мужской): Три-двенадцать.", settings=settings)
        voices = resolve_voice(p, _bites())
        v = voices[0]
        self.assertIn("<IMAGE_2> (Lin-Wei-ming)", v.descriptor)
        self.assertNotIn("55", v.descriptor)
        self.assertNotIn("gruff", v.descriptor)

    def test_more_than_three_speakers_capped_and_logged(self):
        dialogue = "Ху (мужской): Раз.\nГуо (male): Два.\nЛинь (мужской): Три.\nЮань (мужской): Четыре."
        with self.assertLogs(level=logging.WARNING):
            voices = resolve_voice(_panel(dialogue=dialogue, settings=REAL_SETTINGS), _bites())
        self.assertEqual(len(voices), 3)

    def test_no_dialogue_no_voices(self):
        self.assertEqual(resolve_voice(_panel(dialogue=""), _bites()), [])


class VoiceRenderTests(unittest.TestCase):
    def test_descriptors_rendered_in_audio_block(self):
        # Speaker nick and settings.actor disagree (real CRAB data shape):
        # render the nick-bound descriptor, not the foreign profile.
        p = _panel(dialogue="Линь (мужской): Три-двенадцать.", settings=REAL_SETTINGS)
        voices = resolve_voice(p, _bites())
        prompt = build_video_prompt(p, _bites(), voices, 4)
        audio = prompt.split("AUDIO:")[1]
        self.assertIn("Линь", audio)
        self.assertIn("tired, analytical", audio)
        self.assertIn("<IMAGE_2>", audio)

    def test_no_voices_audio_block_unchanged(self):
        p = _panel(settings=REAL_SETTINGS)
        a = build_video_prompt(p, _bites(), resolve_voice(p, _bites()), 4).split("AUDIO:")[1]
        b = build_video_prompt(p, _bites(), [], 4).split("AUDIO:")[1]
        # descriptor line present in (a), absent in (b); dialogue unaffected
        self.assertIn("Voice:", a)
        self.assertNotIn("Voice:", b)
        self.assertIn("Ху (мужской): Опять учения.", a)
        self.assertIn("Ху (мужской): Опять учения.", b)


if __name__ == "__main__":
    unittest.main()
