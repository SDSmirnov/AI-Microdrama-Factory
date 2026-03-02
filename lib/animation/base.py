"""
BaseAnimator abstract class for animation backends.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


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
