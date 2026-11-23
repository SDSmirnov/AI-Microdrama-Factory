"""Best-of-attempts promotion: never let a REFINEMENT make a panel worse.

MEASURED PROBLEM (2026-11-11, production QA->refine cycle):
  seedream   attempt1 fid=5 -> attempt2 fid=4   (worse)
  minimax    attempt1 fid=6 -> attempt2 fid=5   (worse)
  minimax    turn 2 introduced "extra arm" AND "duplicated prop"
  nano-banana the edit produced a DUPLICATE RIFLE

The loop in cmd_panel_by_panel_qa promoted every refined panel
UNCONDITIONALLY, so a worse edit replaced a better render and the panel
ended the run worse than it started.

Two fixes, both FREE (no extra API calls - the QA at each attempt already
measures the current panel):

1. BEST-OF-ATTEMPTS. Track the best-scoring version seen during the
   attempt loop and restore it at the end. A panel that never improves
   keeps its best version instead of its last one.

2. NEW-ARTIFACT REJECTION. An edit that introduces a defect the original
   did not have is REJECTED - the original is kept. The QA result carries
   `critical_artifacts` (lib/studio/qa_gate.py), so the comparison is
   against the critical classes only (a minor note like "radio LED still
   green" should not veto an otherwise-good edit).
"""
from typing import Optional

# The four scored axes, all 0-10 and higher-is-better.
SCORED_AXES = ("fidelity", "character_consistency", "composition_match",
                "dramatic_intensity")


def panel_score(result: dict) -> float:
    """A comparable score for one QA verdict.

    A panel that PASSES QA outranks any scored panel, so it gets a large
    bonus rather than being compared on the axes alone.
    """
    if not isinstance(result, dict):
        return -1.0
    total = 0.0
    for axis in SCORED_AXES:
        try:
            total += float(result.get(axis, 0) or 0)
        except (TypeError, ValueError):
            pass
    if not result.get("needs_refinement"):
        total += 1000.0
    return total


def introduced_critical_artifacts(before: dict, after: dict) -> list[str]:
    """Critical artifacts present AFTER the edit but not BEFORE it."""
    def crit(r):
        if not isinstance(r, dict):
            return set()
        tagged = r.get("critical_artifacts")
        if tagged:
            return set(tagged)
        from lib.studio.qa_gate import critical_artifacts
        return set(critical_artifacts(r.get("artifacts")))

    return sorted(crit(after) - crit(before))


class BestPanelKeeper:
    """Holds the best-scoring panel version across a QA->refine loop.

    Usage:
        keeper = BestPanelKeeper(panel_path)
        keeper.consider(panel_path, qa_result)   # after each QA
        keeper.restore_if_better()                # at the end
    """

    def __init__(self, panel_path):
        self.panel_path = panel_path
        self.best_score: Optional[float] = None
        self.best_copy = panel_path.with_name(
            panel_path.stem + ".__best__.png")
        self.best_result: Optional[dict] = None
        self.rejected = 0

    def consider(self, current_path, qa_result: dict) -> bool:
        """Record the current version if it is the best so far.

        Returns True if this version was kept as the best.
        """
        score = panel_score(qa_result)
        if self.best_score is None or score > self.best_score:
            self.best_score = score
            self.best_result = qa_result
            try:
                self.best_copy.write_bytes(current_path.read_bytes())
            except OSError:
                pass
            return True
        return False

    def reject_edit(self, before: dict, after: dict) -> list[str]:
        """Record that an edit introduced new critical defects.

        Returns the new artifacts (empty = the edit is acceptable).
        """
        new = introduced_critical_artifacts(before, after)
        if new:
            self.rejected += 1
        return new

    def restore_if_better(self) -> bool:
        """Put the best-scoring version back as the panel.

        Returns True if a restore happened.
        """
        if not self.best_copy.exists():
            return False
        try:
            best_bytes = self.best_copy.read_bytes()
            cur_bytes = self.panel_path.read_bytes()
        except OSError:
            return False
        if best_bytes == cur_bytes:
            self._cleanup()
            return False
        self.panel_path.write_bytes(best_bytes)
        self._cleanup()
        return True

    def _cleanup(self):
        try:
            if self.best_copy.exists():
                self.best_copy.unlink()
        except OSError:
            pass
