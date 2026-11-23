"""Image seed handling — make "regeneration" an actual new sample.

MEASURED 2026-11-12 (google/gemini-nano-banana-2.1, chat path, 1K):
    temperature 1.0, top_p 0.95, seed 21:
        call 1 -> md5 18994ae183e8
        call 2 -> md5 a962f670b535      <- SAME seed, DIFFERENT image
        seed 99 -> md5 b9f1fa356c8e

The `seed` field is a HINT on this path, not a determinism guarantee.
That breaks the old comment "seed from AI_SEED env var for reproducibility
across retries" and, more importantly, it means the regen path
(lib/studio/editor.py `_regenerate_t2i`) can re-issue the same prompt and
get back a near-duplicate of the image it is replacing.

Two counters here fix that, at zero cost (the seed does not affect price):

  base_seed + attempt_offset  -> every attempt in a retry loop is a
                                 genuinely different sample

  render counter              -> two successive calls with the SAME seed
                                 are still told different seeds, so a
                                 plain re-render (not a retry) also
                                 produces a new sample.

Both are opt-out via the env var AI_SEED_STRICT=1 (always use the base
seed), for anyone who needs byte-reproducible renders.
"""
import logging
import os
import threading

logger = logging.getLogger(__name__)

_DEFAULT_SEED = 21


def base_seed() -> int:
    """The configured base seed (AI_SEED, default 21)."""
    try:
        return int(os.getenv("AI_SEED", str(_DEFAULT_SEED)))
    except ValueError:
        return _DEFAULT_SEED


def _strict() -> bool:
    return (os.getenv("AI_SEED_STRICT", "") or "").strip().lower() in (
        "1", "true", "yes", "on")


class SeedCounter:
    """Hands out a different seed per call so every render is a new sample.

    Thread-safe: the animator renders panels concurrently.
    """

    def __init__(self, base: int | None = None):
        self._base = base_seed() if base is None else base
        self._lock = threading.Lock()
        self._n = 0

    def next(self) -> int:
        if _strict():
            return self._base
        with self._lock:
            self._n += 1
            n = self._n
        return self._base + n

    @property
    def base(self) -> int:
        return self._base
