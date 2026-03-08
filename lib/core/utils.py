"""
Shared pipeline utilities.
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path("cinematic_render")
# Override per project: export AI_REF_DIR=ref_my_novel
DEFAULT_REF_DIR = Path(os.getenv('AI_REF_DIR', 'ref_thriller'))


def is_portrait(aspect_ratio: str) -> bool:
    """Return True if aspect ratio is portrait (height > width), e.g. '9:16', '2:3'."""
    try:
        w, h = (int(x) for x in aspect_ratio.split(':'))
        return h > w
    except (ValueError, AttributeError):
        return True  # assume portrait on parse failure


def safe_name(name: str) -> str:
    """Canonical filesystem-safe name: lowercase, underscored, no quotes or slashes."""
    return name.replace("/", "-").replace("'", " ").replace('"', '').replace(" ", "_").lower()


def load_metadata(path: Path) -> dict:
    """Load animation_metadata.json; raises FileNotFoundError if missing."""
    if not path.exists():
        raise FileNotFoundError(f"Metadata not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write(path: Path, content: str, encoding: str = 'utf-8'):
    """Write content to path atomically via tmp-file + rename (POSIX-safe)."""
    tmp = path.with_suffix('.tmp')
    try:
        tmp.write_text(content, encoding=encoding)
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def panel_boxes(w: int, h: int, cols: int, rows: int, panels_count: int) -> list[tuple]:
    """
    Compute (left, top, right, bottom) crop boxes for a grid image.
    Applies a 1% inset per edge to drop artifact borders.
    Returns at most `panels_count` boxes in row-major order.
    Warns if image dimensions are not evenly divisible by the grid.
    """
    if w % cols != 0 or h % rows != 0:
        logger.warning(
            f"Grid {w}x{h} not evenly divisible by {cols}x{rows} — "
            f"panels will have 1px drift on right/bottom edges"
        )
    pw, ph = w // cols, h // rows
    cx, cy = max(1, pw // 100), max(1, ph // 100)
    boxes: list[tuple] = []
    for r in range(rows):
        for c in range(cols):
            if len(boxes) >= panels_count:
                return boxes
            boxes.append((c * pw + cx, r * ph + cy, (c + 1) * pw - cx, (r + 1) * ph - cy))
    return boxes


def grid_dims(panels_per_scene: int) -> tuple[int, int]:
    """Return (cols, rows) grid layout for a given panel count."""
    if panels_per_scene <= 0:
        raise ValueError(f"panels_per_scene must be > 0, got {panels_per_scene}")
    if panels_per_scene == 9:
        return 3, 3
    elif panels_per_scene == 6:
        return 3, 2
    elif panels_per_scene == 4:
        return 2, 2
    else:
        cols, rows = 3, (panels_per_scene + 2) // 3
        logger.warning(
            f"grid_dims: non-standard panels_per_scene={panels_per_scene}, "
            f"using {cols}x{rows} layout ({cols * rows} cells for {panels_per_scene} panels)"
        )
        return cols, rows
