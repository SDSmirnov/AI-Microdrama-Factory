"""
LogDebugLLM — stores every prompt to disk for manual testing in web chatbots.

Writes to: cinematic_render/debug_llm/prompts/<caller>_<YMDhm>.md
Caller is auto-detected from the call stack (first lib/studio frame).
make_image / make_video raise NotImplementedError — debug mode is text-only.
"""
import inspect
import json
import logging
from datetime import datetime
from pathlib import Path

from lib.llm.base import BaseLLM

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path("cinematic_render/debug_llm/prompts")


def _caller_name() -> str:
    """Walk the call stack to find the first lib/studio frame as caller label."""
    for frame_info in inspect.stack():
        fname = frame_info.filename.replace("\\", "/")
        if "/lib/studio/" in fname:
            module = Path(fname).stem
            func = frame_info.function
            return f"{module}.{func}"
    # Fallback: immediate non-debug caller
    for frame_info in inspect.stack():
        fname = frame_info.filename.replace("\\", "/")
        if "/lib/llm/debug" not in fname and "__main__" not in fname:
            return Path(fname).stem
    return "unknown"


class LogDebugLLM(BaseLLM):
    """Dumps prompts to markdown files; returns empty stubs so the pipeline continues."""

    def __init__(self, output_dir: Path = _OUTPUT_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _write(self, caller: str, prompt: str, schema: dict = None, extra: str = "") -> Path:
        ts = datetime.now().strftime("%Y%m%d%H%M")
        filename = f"{caller}_{ts}.md"
        path = self.output_dir / filename

        parts = [f"# {caller} @ {ts}\n"]
        if extra:
            parts.append(f"## Context\n{extra}\n")
        if schema:
            parts.append(f"## JSON Schema\n```json\n{json.dumps(schema, indent=2, ensure_ascii=False)}\n```\n")
        parts.append(f"## Prompt\n{prompt}\n")

        path.write_text("".join(parts), encoding="utf-8")
        logger.info(f"[LogDebugLLM] saved → {path}")
        return path

    def make_json(self, prompt: str, schema: dict = None) -> dict:
        caller = _caller_name()
        self._write(caller, prompt, schema=schema)
        return {}

    def make_image(self, prompt: str, refs: list = None,
                   aspect_ratio: str = "9:16", image_size: str = "2K",
                   temperature: float = None) -> bytes:
        caller = _caller_name()
        self._write(caller, prompt + f"REFS: {refs}", extra=f"aspect_ratio={aspect_ratio}, image_size={image_size}")
        raise NotImplementedError("LogDebugLLM: image generation not supported — prompt saved to disk")

    def analyze_image(self, image, prompt: str, refs=None, schema: dict = None) -> dict:
        caller = _caller_name()
        self._write(caller, prompt, schema=schema, extra="[analyze_image — image not captured]")
        return {}

    def analyze_video(self, video, prompt: str, refs=None, schema: dict = None) -> dict:
        caller = _caller_name()
        self._write(caller, prompt, schema=schema, extra="[analyze_video — video not captured]")
        return {}
