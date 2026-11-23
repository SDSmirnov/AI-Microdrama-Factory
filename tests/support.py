"""Pure fixture builders shared by tests. Every call creates its own Project and files; nothing is shared between tests."""
import json

from lib.core.project import Project


class StubLLM:
    """Records generate_video kwargs; returns fake MP4 bytes."""

    def __init__(self):
        self.calls = []

    def generate_video(self, **kwargs):
        self.calls.append(kwargs)
        return b"MP4VIDEO"


def make_ref_project(root, refs, *, desc="wide view."):
    """Build a Project with ref_thriller JSONs/PNGs for (name, type) pairs under root."""
    ref_dir = root / "ref_thriller"
    ref_dir.mkdir(parents=True, exist_ok=True)
    project = Project()
    project.ref_dir = ref_dir
    project.character_info = {}
    project.character_images = {}
    for name, kind in refs:
        slug = name.lower()
        info = {"name": name, "type": kind,
                "video_visual_desc": f"{name} visuals.",
                "visual_desc": f"{name} {desc}"}
        (ref_dir / f"{slug}.json").write_text(json.dumps(info))
        (ref_dir / f"{slug}.png").write_bytes(b"PNG" + name.encode())
        project.character_info[name] = info
        project.character_images[name] = str(ref_dir / f"{slug}.png")
    return project
