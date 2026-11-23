"""Render engine selection: AI_RENDER3D=blender (default) | pyvista | auto (pyvista when installed, else blender)."""
import os
from pathlib import Path
from typing import Protocol

from lib.studio.render3d.engines.blender import BlenderEngine
from lib.studio.render3d.engines.pyvista import PyVistaEngine
from lib.studio.render3d.scene import Scene


class Engine(Protocol):
    name: str

    def available(self) -> bool: ...

    def render(self, jobs: list[tuple[Scene, Path]]) -> None: ...


ENGINES = ('blender', 'pyvista', 'auto')


def get_engine(name: str | None = None, blender_cmd: str = 'blender') -> Engine:
    name = (name or os.getenv('AI_RENDER3D') or 'blender').strip().lower()
    if name not in ENGINES:
        raise ValueError(f'unknown render engine {name!r}; choose from {list(ENGINES)}')
    if name == 'pyvista' or (name == 'auto' and PyVistaEngine().available()):
        return PyVistaEngine()
    return BlenderEngine(blender_cmd)
