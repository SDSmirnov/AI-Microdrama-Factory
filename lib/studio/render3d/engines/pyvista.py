"""PyVista (VTK) engine: in-process, off-screen; mirrors the Blender engine's lights and two-tier sketch lines."""
import math
import os
from pathlib import Path

from lib.studio.render3d.scene import Scene

# Blender engine lights in VTK terms. Outdoors: world strength 0.52 → ambient, sun strengths 2.3 / 0.55 over π →
# diffuse. Enclosed sets (rooms, car cabins): Blender's walls and roof shadow both suns, which VTK cannot do
# headless (its shadow shader fails under EGL); a brighter ambient with the fill only matches within ~5/255.
WORLD = 0.52
LIGHTS = {  # (ambient, ((rotation x°, rotation z°, intensity), ...))
    'outdoor': (WORLD, ((52, 32, 2.3 / math.pi), (125, -145, 0.55 / math.pi))),
    'enclosed': (0.72, ((125, -145, 0.55 / math.pi),)),
}
CONTOUR = ((0.04, 0.04, 0.05), 1.75)   # silhouettes + open borders: colour, px
CREASE = ((0.09, 0.09, 0.11), 0.95, 35.0)  # interior creases: colour, px, angle°


def _sun_direction(rx: float, rz: float) -> tuple[float, float, float]:
    """Blender sun: local −Z rotated by Euler XYZ (rx, 0, rz)."""
    rx, rz = math.radians(rx), math.radians(rz)
    return -math.sin(rx) * math.sin(rz), math.sin(rx) * math.cos(rz), -math.cos(rx)


def _srgb(c: float) -> int:
    c = min(1.0, max(0.0, c))
    return round(255 * (12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055))


class PyVistaEngine:
    name = 'pyvista'

    def available(self) -> bool:
        try:
            import pyvista  # noqa: F401
        except ImportError:
            return False
        return True

    def render(self, jobs: list[tuple[Scene, Path]]) -> None:
        if not jobs:
            return
        if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
            os.environ.setdefault('VTK_DEFAULT_OPENGL_WINDOW', 'vtkEGLRenderWindow')  # headless: skip the X11 attempt
        import pyvista as pv

        plotter = pv.Plotter(off_screen=True, lighting='none')
        try:
            plotter.set_background([_srgb(WORLD) / 255] * 3)  # Blender's world: white at strength 0.52
            for scene, out in jobs:
                plotter.clear_actors()
                plotter.remove_all_lights()
                ambient, suns = LIGHTS['outdoor' if scene.outdoor else 'enclosed']
                for rx, rz, intensity in suns:
                    dx, dy, dz = _sun_direction(rx, rz)
                    plotter.add_light(pv.Light(position=(-dx, -dy, -dz), focal_point=(0, 0, 0), intensity=intensity,
                                               light_type='scene light', positional=False))
                plotter.window_size = (scene.view.width_px, scene.view.height_px)
                mesh = self._polydata(scene)
                plotter.add_mesh(mesh, scalars='rgb', rgb=True, ambient=ambient, diffuse=1.0, specular=0.0,
                                 smooth_shading=False)
                colour, width, angle = CREASE
                self._lines(plotter, mesh.extract_feature_edges(angle, boundary_edges=False, manifold_edges=False,
                                                                non_manifold_edges=False), colour, width)
                cam = plotter.camera
                v = scene.view
                cam.position, cam.focal_point, cam.up = v.position, v.target, (0, 0, 1)
                cam.SetUseHorizontalViewAngle(True)
                cam.view_angle = v.hfov
                cam.clipping_range = (v.clip_start or 0.04, 500.0)
                colour, width = CONTOUR
                self._lines(plotter, self._silhouette(mesh, cam, pv), colour, width)
                self._lines(plotter, mesh.extract_feature_edges(boundary_edges=True, feature_edges=False,
                                                                manifold_edges=False, non_manifold_edges=False), colour, width)
                plotter.screenshot(str(out))
                if not Path(out).exists() or not Path(out).stat().st_size:
                    raise RuntimeError(f'pyvista produced no image for {out}')
        finally:
            plotter.close()

    @staticmethod
    def _lines(plotter, lines, colour, width) -> None:
        if lines.n_points:
            plotter.add_mesh(lines, color=colour, line_width=width)

    @staticmethod
    def _polydata(scene: Scene):
        import numpy as np
        import pyvista as pv

        points, cells, colours = [], [], []
        for m in scene.meshes:
            base = len(points)
            points.extend(m.verts)
            rgb = [_srgb(c) for c in m.color]
            for face in m.faces:
                cells.extend((len(face), *(base + i for i in face)))
                colours.append(rgb)
        mesh = pv.PolyData(np.asarray(points, float), np.asarray(cells))
        mesh.cell_data['rgb'] = np.asarray(colours, np.uint8)
        return mesh

    @staticmethod
    def _silhouette(mesh, camera, pv):
        import vtk

        sil = vtk.vtkPolyDataSilhouette()
        sil.SetInputData(mesh)
        sil.SetCamera(camera)
        sil.SetEnableFeatureAngle(False)
        sil.Update()
        return pv.wrap(sil.GetOutput())
