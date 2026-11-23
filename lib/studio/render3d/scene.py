"""What an engine renders: world-space meshes and one camera. Serializable, so out-of-process engines get it as JSON."""
from dataclasses import dataclass, field


@dataclass
class Mesh:
    name: str
    verts: list[tuple[float, float, float]]
    faces: list[tuple[int, ...]]
    color: tuple[float, float, float]   # linear RGB
    group: str = ''                      # anchor object id, for culling


@dataclass(frozen=True)
class View:
    position: tuple[float, float, float]
    target: tuple[float, float, float]
    hfov: float                          # horizontal, degrees; the vertical follows the pixel aspect
    width_px: int
    height_px: int
    clip_start: float | None = None      # near plane; wall views cut the room here


@dataclass
class Scene:
    meshes: list[Mesh] = field(default_factory=list)
    view: View | None = None
    outdoor: bool = False                # no walls or roof between the suns and the set

    def to_dict(self) -> dict:
        return {'meshes': [m.__dict__ for m in self.meshes], 'view': self.view.__dict__, 'outdoor': self.outdoor}
