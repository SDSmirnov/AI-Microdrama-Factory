"""Promotion rules: a refinement must never make a panel worse.

MEASURED PROBLEM (2026-11-11, production QA->refine cycle):
  seedream   attempt1 fid=5 -> attempt2 fid=4   (worse, and promoted)
  minimax    attempt1 fid=6 -> attempt2 fid=5   (worse, and promoted)
  minimax    turn 2 introduced "extra arm" AND "duplicated prop"
  nano-banana the edit produced a DUPLICATE RIFLE

The loop promoted every refined panel unconditionally. These tests lock in
the fix: keep the best-scoring version, and reject an edit that introduces
a defect the original did not have.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.studio.promotion import (BestPanelKeeper, introduced_critical_artifacts,
                                  panel_score)


def _verdict(fid=5, cons=5, comp=5, dram=5, needs=True, artifacts=None,
             critical=None):
    r = {"fidelity": fid, "character_consistency": cons,
         "composition_match": comp, "dramatic_intensity": dram,
         "artifacts": artifacts or [], "needs_refinement": needs}
    if critical is not None:
        r["critical_artifacts"] = critical
    return r


class PanelScoreTests(unittest.TestCase):
    def test_passing_panel_outranks_a_failing_one(self):
        failing = _verdict(fid=9, cons=9, comp=9, dram=9, needs=True)
        passing = _verdict(fid=5, cons=5, comp=5, dram=5, needs=False)
        self.assertGreater(panel_score(passing), panel_score(failing))

    def test_higher_axes_score_higher(self):
        low = _verdict(fid=4, cons=4, comp=4, dram=4)
        high = _verdict(fid=6, cons=6, comp=6, dram=6)
        self.assertGreater(panel_score(high), panel_score(low))

    def test_non_dict_is_safe(self):
        self.assertEqual(panel_score(None), -1.0)


class IntroducedArtifactTests(unittest.TestCase):
    def test_new_critical_artifact_is_detected(self):
        before = _verdict(artifacts=["radio LED still green"])
        after = _verdict(artifacts=["radio LED still green",
                                    "wrong shot scale: WS instead of MS"])
        new = introduced_critical_artifacts(before, after)
        self.assertEqual(len(new), 1)
        self.assertIn("shot scale", new[0])

    def test_pre_existing_artifact_is_not_new(self):
        before = _verdict(artifacts=["wrong shot scale: WS instead of MS"])
        after = _verdict(artifacts=["wrong shot scale: WS instead of MS"])
        self.assertEqual(introduced_critical_artifacts(before, after), [])

    def test_minor_artifact_is_not_critical(self):
        before = _verdict(artifacts=["radio LED still green"])
        after = _verdict(artifacts=["radio LED still green",
                                    "fist raised rather than lowered"])
        self.assertEqual(introduced_critical_artifacts(before, after), [])

    def test_uses_the_tagged_critical_list_when_present(self):
        before = _verdict(critical=[])
        after = _verdict(critical=["missing character: Hu is absent"])
        new = introduced_critical_artifacts(before, after)
        self.assertEqual(len(new), 1)


class BestPanelKeeperTests(unittest.TestCase):
    def _png(self, path, byte):
        path.write_bytes(byte)
        return path

    def test_keeps_the_best_scoring_version(self):
        import tempfile
        from pathlib import Path as P
        with tempfile.TemporaryDirectory() as d:
            panel = P(d) / "001_01_static.png"
            self._png(panel, b"AAA")
            keeper = BestPanelKeeper(panel)
            self.assertTrue(keeper.consider(panel, _verdict(fid=6)))
            self._png(panel, b"BBB")           # a worse edit was promoted
            self.assertFalse(keeper.consider(panel, _verdict(fid=4)))
            self.assertTrue(keeper.restore_if_better())
            self.assertEqual(panel.read_bytes(), b"AAA")

    def test_does_not_restore_when_the_last_version_was_the_best(self):
        import tempfile
        from pathlib import Path as P
        with tempfile.TemporaryDirectory() as d:
            panel = P(d) / "001_01_static.png"
            self._png(panel, b"AAA")
            keeper = BestPanelKeeper(panel)
            keeper.consider(panel, _verdict(fid=4))
            self._png(panel, b"BBB")
            keeper.consider(panel, _verdict(fid=8))
            self.assertFalse(keeper.restore_if_better())
            self.assertEqual(panel.read_bytes(), b"BBB")

    def test_a_passing_version_beats_a_higher_scoring_failing_one(self):
        import tempfile
        from pathlib import Path as P
        with tempfile.TemporaryDirectory() as d:
            panel = P(d) / "001_01_static.png"
            self._png(panel, b"AAA")
            keeper = BestPanelKeeper(panel)
            keeper.consider(panel, _verdict(fid=9, needs=True))
            self._png(panel, b"BBB")
            keeper.consider(panel, _verdict(fid=5, needs=False))
            # The passing version is recorded as the best, so it is what
            # would be restored.
            self.assertEqual(keeper.best_copy.read_bytes(), b"BBB")
            # Nothing to restore: the best IS the current file.
            self.assertFalse(keeper.restore_if_better())
            self.assertEqual(panel.read_bytes(), b"BBB")

    def test_cleanup_removes_the_temp_copy(self):
        import tempfile
        from pathlib import Path as P
        with tempfile.TemporaryDirectory() as d:
            panel = P(d) / "001_01_static.png"
            self._png(panel, b"AAA")
            keeper = BestPanelKeeper(panel)
            keeper.consider(panel, _verdict(fid=6))
            self.assertTrue(keeper.best_copy.exists())
            keeper.restore_if_better()
            self.assertFalse(keeper.best_copy.exists())


if __name__ == "__main__":
    unittest.main()
