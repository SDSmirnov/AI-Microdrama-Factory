"""Quickplay needs animation_episodes.json and must fail before writing output."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.studio.quickplay import build_quickplay


class BuildQuickplayTests(unittest.TestCase):
    def test_metadata_without_episodes_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'animation_metadata.json'
            src.write_text(json.dumps({'scenes': [{'scene_id': 1}]}), encoding='utf-8')
            out = Path(tmp) / 'quickplay.json'
            with self.assertRaisesRegex(ValueError, 'animation_episodes.json'):
                build_quickplay(src, out, llm=None)
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
