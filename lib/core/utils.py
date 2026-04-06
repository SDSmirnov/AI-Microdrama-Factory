"""
Shared pipeline utilities.
"""
import json
import logging
import os
from pathlib import Path

from PIL import Image

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


# (cols, rows, grid_ar) — grid_ar is the T2I API aspect ratio for a grid of 9:16 panels.
# Derivation: grid_ar = (cols×9):(rows×16), snapped to nearest supported T2I AR.
# 4→2×2=9:16(exact), 6→3×2=4:5(5.2% off), 9→3×3=9:16(exact),
# 10→5×2=4:3(5.2% off), 12→4×3=3:4(exact). 8 dropped (11% error).
_GRID_TABLE: dict[int, tuple[int, int, str]] = {
    4:  (2, 2, "9:16"),
    6:  (3, 2, "4:5"),
    9:  (3, 3, "9:16"),
    10: (5, 2, "4:3"),
    12: (4, 3, "3:4"),
}
PANEL_COUNT_OPTIONS: list[int] = sorted(_GRID_TABLE)


def grid_dims(panel_count: int) -> tuple[int, int, str]:
    """Return (cols, rows, grid_ar) for the given panel count.

    grid_ar is the T2I API aspect ratio to request for the composite grid image.
    Raises ValueError for unsupported counts.
    """
    if panel_count not in _GRID_TABLE:
        raise ValueError(
            f"Unsupported panel_count={panel_count}. Allowed: {PANEL_COUNT_OPTIONS}"
        )
    return _GRID_TABLE[panel_count]


def pad_to_ar(img: Image.Image, target_ar: str = "9:16") -> Image.Image:
    """Letterbox or pillarbox img to exact target_ar with black fill.

    Returns the original image object unchanged if already at the correct ratio.
    Returns a new RGB image otherwise.
    """
    tw, th = (int(x) for x in target_ar.split(":"))
    w, h = img.size
    if w * th == h * tw:
        return img
    if w / h > tw / th:  # too wide → add top/bottom bars
        new_h = round(w * th / tw)
        out = Image.new("RGB", (w, new_h), (0, 0, 0))
        out.paste(img, (0, (new_h - h) // 2))
    else:                # too tall → add left/right bars
        new_w = round(h * tw / th)
        out = Image.new("RGB", (new_w, h), (0, 0, 0))
        out.paste(img, ((new_w - w) // 2, 0))
    return out
