"""
BaseAnimator abstract class for animation backends.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

# Injected into every animation prompt regardless of backend.
# Prevents uncanny-valley artifacts that video models add automatically to
# tense/emotional scenes (sweat, tears, breath vapor, oral fluids, theatrical faces).
ANIMATION_PROHIBITIONS = (
    "CRITICALLY FORBIDDEN: object morphing, adding new objects, adding new actors.\n"
    "NO sweat — no dripping, beading, shiny skin, or wet clothing.\n"
    "NO tears — no tear tracks, glistening eyes, or eyes filling with liquid.\n"
    "NO breath vapor or mouth condensation — no visible exhale cloud.\n"
    "NO oral liquids — no saliva, drool, foam, or spittle.\n"
    "NO theatrical facial extremes: no bared teeth in anger, no sustained gaping mouth, "
    "no frozen wide-eye terror held beyond 1s.\n"
)


def clip_path_for_panel(start_path: Path, out_dir: Path) -> Path:
    """Return the canonical clip path for a panel image.

    Panel images are named ``{scene:03d}_{panel:02d}_{frame}.png``; clips
    must be named ``clip_{scene:02d}_{panel:03d}.mp4`` so ``studio.cutter``
    can find them. Non-standard stems fall back to the legacy stem-derived
    id.
    """
    parts = start_path.stem.split("_")
    if len(parts) >= 2:
        try:
            return out_dir / f"clip_{int(parts[0]):02d}_{int(parts[1]):03d}.mp4"
        except ValueError:
            pass
    legacy = start_path.stem.replace("_start", "").replace("_static", "")
    return out_dir / f"clip_{legacy}.mp4"


class BaseAnimator(ABC):
    """Abstract base for video animation backends."""

    @abstractmethod
    def animate(
        self,
        start_path: Path,
        end_path: Optional[Path],
        meta: dict,
        index: int,
        out_dir: Path,
    ) -> Optional[Path]:
        """
        Animate a panel from start frame to end frame.

        start_path: path to start PNG
        end_path:   path to end PNG (or None for image-to-video)
        meta:       panel metadata dict
        index:      sequential index for logging
        out_dir:    directory to write the output clip

        Returns path to the output clip, or None on failure.
        """
        ...
