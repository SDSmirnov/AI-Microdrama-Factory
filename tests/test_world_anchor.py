"""Real-world anchor: `styles` writes it into setting.md; the bible and casting read the book in its era."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.core.prompts import world_anchor
from lib.studio.stylist import WORLD_ANCHOR_SCHEMA, analyze_anchor, anchor_markdown, with_anchor

ANCHOR = {'analog': 'Japan, Sengoku period, 1581 (Tensho 9)', 'evidence': ['Эпоха Тэнсё… Девятый год эпохи'],
          'departures': ['resurrection (fukkatsu) is a karmic law'],
          'material_culture': ['tatami floors', 'paper lanterns'],
          'not_in_this_world': ['armchairs', 'fireplaces', 'revolvers']}
SETTING = "# World & Setting Reference\n\n## Setting\nFeudal Japan\n\n## Protagonist\n- **Name**: Reiden\n"


class WorldAnchorTests(unittest.TestCase):
    def test_section_round_trips_and_is_empty_when_absent(self):
        body = world_anchor(with_anchor(SETTING, ANCHOR))
        self.assertTrue(body.startswith('- **Analog**: Japan, Sengoku period, 1581 (Tensho 9)'))
        self.assertIn('- **Not in this world**: armchairs; fireplaces; revolvers', body)
        self.assertEqual(world_anchor(SETTING), '')

    def test_rewrite_replaces_the_section_and_keeps_the_rest(self):
        once = with_anchor(SETTING, ANCHOR)
        twice = with_anchor(once, {**ANCHOR, 'analog': 'Japan, 1582'})
        self.assertEqual(twice.count('## Real-world anchor'), 1)
        self.assertIn('Japan, 1582', world_anchor(twice))
        self.assertIn('## Protagonist\n- **Name**: Reiden', twice)
        middle = SETTING.replace('## Protagonist', anchor_markdown(ANCHOR) + '\n## Protagonist')
        self.assertEqual(with_anchor(middle, ANCHOR).count('## Protagonist'), 1)
        self.assertIn('## Protagonist', with_anchor(middle, ANCHOR))

    def test_anchor_only_analysis_asks_for_evidence_and_rejects_an_empty_reply(self):
        class Fake:
            def __init__(self, reply):
                self.reply, self.prompt = reply, None

            def make_json(self, prompt, schema):
                self.prompt, self.schema = prompt, schema
                return self.reply
        llm = Fake(ANCHOR)
        self.assertEqual(analyze_anchor('Эпоха Тэнсё. ' * 3, llm), ANCHOR)
        self.assertIs(llm.schema, WORLD_ANCHOR_SCHEMA)
        self.assertIn('quoting the lines that date or place it', llm.prompt)
        self.assertIn('Эпоха Тэнсё.', llm.prompt)
        self.assertIsNone(analyze_anchor('x', Fake({})))
        self.assertIsNone(analyze_anchor('x', Fake(None)))


if __name__ == '__main__':
    unittest.main()
