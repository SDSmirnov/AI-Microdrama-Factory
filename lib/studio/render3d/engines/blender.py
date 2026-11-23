"""Blender engine: one background Blender process per batch, Freestyle sketch lines."""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from lib.studio.render3d.scene import Scene

ENTRY = Path(__file__).with_name('_blender_entry.py')
TIMEOUT_S = (60, 30)  # start-up + per scene; a scene takes ~7–13 s


class BlenderEngine:
    name = 'blender'

    def __init__(self, cmd: str = 'blender'):
        self.cmd = cmd

    def available(self) -> bool:
        return shutil.which(self.cmd) is not None

    def render(self, jobs: list[tuple[Scene, Path]]) -> None:
        """Writes every output or raises RuntimeError; outputs of a failed batch are not to be trusted."""
        if not jobs:
            return
        with tempfile.TemporaryDirectory(prefix='render3d-blender-') as tmp:
            spec = Path(tmp) / 'jobs.json'
            spec.write_text(json.dumps({'jobs': [{'scene': s.to_dict(), 'output': str(out)} for s, out in jobs]}),
                            encoding='utf-8')
            try:
                proc = subprocess.run([self.cmd, '-b', '--python', str(ENTRY), '--', str(spec)], capture_output=True,
                                      text=True, timeout=TIMEOUT_S[0] + TIMEOUT_S[1] * len(jobs))
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError(f'blender render failed: {exc}') from exc
        if proc.returncode != 0:
            raise RuntimeError('blender render failed: ' + ' | '.join((proc.stderr or proc.stdout).strip().splitlines()[-10:]))
        missing = [str(out) for _, out in jobs if not Path(out).exists() or not Path(out).stat().st_size]
        if missing:
            raise RuntimeError(f'blender produced no image for {missing[:3]}')
