"""
ManualLLM — interactive backend for manual testing / prompt inspection.

Each call:
  1. Builds the full prompt (system + user + schema + final instruction).
  2. Saves it to cinematic_render/manual_llm/<caller>_<YMDhm>.md and prints
     the file path — open the file when the chatbot input field is too small.
  3. Prints the prompt to stdout.
  4. Waits for a response from stdin:
     - make_json  / make_text  : type content + Ctrl-D, OR enter a file path.
     - make_image / edit_image : enter a single file path to a PNG/JPG.
     - analyze_image           : same as make_json.

PIL Image refs are saved as temp PNGs so the user can open/attach them.
"""
import inspect
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from lib.llm.base import BaseLLM, parse_json

_OUTPUT_DIR = Path("cinematic_render/manual_llm")
_SEP = "=" * 72
_THIN = "-" * 72


def _caller_name() -> str:
    """First lib/studio frame on the call stack, same logic as LogDebugLLM."""
    for fi in inspect.stack():
        fname = fi.filename.replace("\\", "/")
        if "/lib/studio/" in fname:
            return f"{Path(fname).stem}.{fi.function}"
    for fi in inspect.stack():
        fname = fi.filename.replace("\\", "/")
        if "/lib/llm/manual" not in fname and "__main__" not in fname:
            return Path(fname).stem
    return "unknown"


def _save_prompt(title: str, body: str) -> Path:
    """Save prompt body to a dated markdown file; return the path."""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    caller = _caller_name()
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    path = _OUTPUT_DIR / f"{caller}_{ts}.md"
    path.write_text(f"# ManualLLM › {title}\n\n{body}", encoding="utf-8")
    return path


def _display(title: str, body: str):
    """Save prompt to file, print path + full body to stdout."""
    path = _save_prompt(title, body)
    print(f"\n{_SEP}", flush=True)
    print(f"  ManualLLM › {title}  |  saved → {path}", flush=True)
    print(_SEP, flush=True)
    print(body, flush=True)


def _collect_refs(refs) -> tuple[str, list[str]]:
    """
    Return (markdown_block, image_paths).

    Saves PIL Images to temp PNGs; inline strings are embedded in the block.
    image_paths lists saved temp file paths for the terminal summary line.
    """
    if not refs:
        return "", []

    parts = [f"\n{_THIN}\n## ATTACHED REFS\n"]
    image_paths = []
    for i, ref in enumerate(refs):
        if isinstance(ref, str):
            parts.append(f"[{i}] (text)\n{ref}\n")
        else:
            try:
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".png", delete=False, prefix=f"manual_ref_{i}_"
                )
                ref.save(tmp.name)
                parts.append(f"[{i}] (image) → {tmp.name}  size={ref.size}\n")
                image_paths.append(tmp.name)
            except Exception as e:
                parts.append(f"[{i}] (image) <could not save: {e}>\n")
    return "".join(parts), image_paths


def _read_response(prompt_hint: str) -> str:
    """
    Read response from stdin.

    Single-line input that is an existing file path → read that file.
    Otherwise read until EOF (Ctrl-D / Ctrl-Z+Enter).
    """
    print(f"\n{_THIN}", flush=True)
    print(f"  ↳ Paste {prompt_hint} then Ctrl-D, OR enter a file path:", flush=True)
    print(_THIN, flush=True)

    lines = []
    try:
        for line in sys.stdin:
            lines.append(line)
    except EOFError:
        pass

    text = "".join(lines).strip()
    if "\n" not in text and text:
        p = Path(text)
        if p.exists() and p.is_file():
            return p.read_text(encoding="utf-8").strip()
    return text


def _read_image_path(hint: str) -> bytes:
    """Read one line as a file path, return raw bytes."""
    print(f"\n{_THIN}", flush=True)
    print(f"  ↳ {hint}", flush=True)
    print(_THIN, flush=True)
    line = sys.stdin.readline().strip()
    p = Path(line)
    if not p.exists():
        raise FileNotFoundError(f"ManualLLM: file not found: {p}")
    return p.read_bytes()


class ManualLLM(BaseLLM):
    """Interactive LLM backend — saves + prints prompts, reads responses from stdin."""

    def __init__(self, system_prompt: str = ""):
        self.system_prompt = system_prompt

    # ------------------------------------------------------------------
    # JSON generation
    # ------------------------------------------------------------------

    def make_json(self, prompt: str, schema: dict = None, max_tokens: int = 32000) -> dict:
        parts = []
        if self.system_prompt:
            parts.append(f"## SYSTEM PROMPT\n{self.system_prompt}\n")
        parts.append(f"## PROMPT\n{prompt}\n")
        if schema:
            parts.append(f"## JSON SCHEMA\n```json\n{json.dumps(schema, indent=2, ensure_ascii=False)}\n```\n")
        parts.append("Output strictly in JSON format.")
        _display("make_json", "\n".join(parts))
        return parse_json(_read_response("JSON response"))

    # ------------------------------------------------------------------
    # Text generation
    # ------------------------------------------------------------------

    def make_text(self, prompt: str, system_prompt: str = None, max_tokens: int = 100000) -> str:
        parts = []
        sys_p = system_prompt or self.system_prompt
        if sys_p:
            parts.append(f"## SYSTEM PROMPT\n{sys_p}\n")
        parts.append(f"## PROMPT\n{prompt}\n")
        _display("make_text", "\n".join(parts))
        return _read_response("text response")

    # ------------------------------------------------------------------
    # Image generation
    # ------------------------------------------------------------------

    def make_image(
        self,
        prompt: str,
        refs: list = None,
        aspect_ratio: str = "9:16",
        image_size: str = "2K",
        temperature: float = None,
    ) -> bytes:
        refs_block, _ = _collect_refs(refs)
        parts = [
            f"## PARAMS\naspect_ratio={aspect_ratio}  image_size={image_size}\n",
            f"## PROMPT\n{prompt}\n",
        ]
        if refs_block:
            parts.append(refs_block)
        _display("make_image", "\n".join(parts))
        return _read_image_path("Enter path to generated PNG/JPG:")

    # ------------------------------------------------------------------
    # Image editing
    # ------------------------------------------------------------------

    def edit_image(
        self,
        src_img,
        prompt: str,
        refs=None,
        aspect_ratio: str = None,
        image_size: str = None,
    ) -> bytes:
        refs_block, _ = _collect_refs(refs)
        src_label = str(src_img) if isinstance(src_img, (str, Path)) else "<binary>"
        if not isinstance(src_img, (str, Path)):
            try:
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix="manual_src_")
                src_img.save(tmp.name)
                src_label = tmp.name
            except Exception:
                pass
        parts = [
            f"## PARAMS\naspect_ratio={aspect_ratio}  image_size={image_size}\n",
            f"## SOURCE IMAGE\n{src_label}\n",
            f"## PROMPT\n{prompt}\n",
        ]
        if refs_block:
            parts.append(refs_block)
        _display("edit_image", "\n".join(parts))
        return _read_image_path("Enter path to edited PNG/JPG:")

    # ------------------------------------------------------------------
    # Image / video analysis
    # ------------------------------------------------------------------

    def analyze_image(self, image, prompt: str, refs=None, schema: dict = None) -> dict:
        items = image if isinstance(image, list) else [image]
        refs_block, _ = _collect_refs(items)
        parts = []
        if refs_block:
            parts.append(refs_block)
        parts.append(f"## PROMPT\n{prompt}\n")
        if schema:
            parts.append(f"## JSON SCHEMA\n```json\n{json.dumps(schema, indent=2, ensure_ascii=False)}\n```\n")
        parts.append("Output strictly in JSON format.")
        _display("analyze_image", "\n".join(parts))
        return parse_json(_read_response("JSON analysis response"))

    def analyze_video(self, video, prompt: str, refs=None, schema: dict = None) -> dict:
        vid_label = str(video) if isinstance(video, (str, Path)) else "<binary blob>"
        refs_block, _ = _collect_refs(refs)
        parts = [f"## VIDEO\n{vid_label}\n"]
        if refs_block:
            parts.append(refs_block)
        parts.append(f"## PROMPT\n{prompt}\n")
        if schema:
            parts.append(f"## JSON SCHEMA\n```json\n{json.dumps(schema, indent=2, ensure_ascii=False)}\n```\n")
        parts.append("Output strictly in JSON format.")
        _display("analyze_video", "\n".join(parts))
        return parse_json(_read_response("JSON analysis response"))
