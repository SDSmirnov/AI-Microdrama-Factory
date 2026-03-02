"""
lib/studio/retoucher.py — AI image editing via BaseLLM backends.

Applies a text instruction to a source image, optionally guided by
one or more reference images.
"""

from pathlib import Path

from lib.llm.base import BaseLLM


def edit_image(
    output_path: str,
    instruction: str,
    source_images: list[str],
    llm: BaseLLM = None,
    aspect_ratio: str = "16:9",
    image_size: str = "2K",
) -> None:
    """
    Edit or composite images using the provided LLM backend.

    Args:
        output_path:   Where to save the result.
        instruction:   Text edit instruction (e.g. "make the sky purple").
        source_images: Paths to images; the first is the target, rest are references.
        llm:           BaseLLM backend that implements edit_image().
        aspect_ratio:  Output aspect ratio (e.g. "16:9", "9:16", "1:1").
        image_size:    Output resolution hint (e.g. "2K", "1K").
    """
    if not llm:
        raise RuntimeError("LLM instance is required")
    if not source_images:
        raise ValueError("source_images must include at least one image path")

    target = Path(source_images[0])
    refs = [Path(p) for p in source_images[1:]]

    # aspect_ratio/image_size are kept for CLI compatibility; backend may ignore them.
    _ = aspect_ratio, image_size

    img_bytes = llm.edit_image(target, instruction, refs=refs)
    if not img_bytes:
        raise RuntimeError("Image edit returned empty response")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(img_bytes)
    print(f"Saved: {out}")
