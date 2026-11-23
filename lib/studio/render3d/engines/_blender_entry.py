"""Runs inside Blender: renders render3d Scene jobs with Freestyle sketch lines.

Run as: blender -b --python _blender_entry.py -- JOBS.json   ({"jobs": [{"scene": Scene.to_dict(), "output": path}]})
Only bpy, mathutils and the standard library are available here.
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def _material(rgb, cache):
    if rgb not in cache:
        mat = bpy.data.materials.new(f'sketch-{len(cache)}')
        mat.use_nodes = True
        mat.diffuse_color = (*rgb, 1)
        bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        bsdf.inputs['Base Color'].default_value = (*rgb, 1)
        bsdf.inputs['Roughness'].default_value = 0.88
        if 'Specular IOR Level' in bsdf.inputs:
            bsdf.inputs['Specular IOR Level'].default_value = 0.15
        cache[rgb] = mat
    return cache[rgb]


def _mesh(m, cache):
    mesh = bpy.data.meshes.new(m['name'])
    mesh.from_pydata(m['verts'], [], m['faces'])
    mesh.update()
    for poly in mesh.polygons:
        poly.use_smooth = False
    mesh.materials.append(_material(tuple(m['color']), cache))
    bpy.context.scene.collection.objects.link(bpy.data.objects.new(m['name'], mesh))


def _setup_render(spec):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.use_freestyle = True
    # Standard view transform keeps category colours vivid and legible.
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0

    # Two-tier architectural pen hierarchy: bold outer contours + fine interior creases
    fs = bpy.context.view_layer.freestyle_settings
    fs.crease_angle = math.radians(35)

    contour = fs.linesets.new('SketchContour')
    contour.select_silhouette = True
    contour.select_border = True
    contour.select_crease = False
    contour.linestyle.color = (0.04, 0.04, 0.05)
    contour.linestyle.thickness = 1.75

    detail = fs.linesets.new('SketchDetail')
    detail.select_silhouette = False
    detail.select_border = False
    detail.select_crease = True
    detail.select_edge_mark = True
    detail.linestyle.color = (0.09, 0.09, 0.11)
    detail.linestyle.thickness = 0.95

    world = bpy.data.worlds.new('sketch_world')
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get('Background')
    background.inputs[0].default_value = (1, 1, 1, 1)
    background.inputs[1].default_value = 0.52

    sun_data = bpy.data.lights.new('key-light', type='SUN')
    sun_data.energy = 2.3
    sun = bpy.data.objects.new('key-light', sun_data)
    bpy.context.scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(52), 0, math.radians(32))

    fill_data = bpy.data.lights.new('fill-light', type='SUN')
    fill_data.energy = 0.55
    if hasattr(fill_data, 'use_shadow'):
        fill_data.use_shadow = False
    fill = bpy.data.objects.new('fill-light', fill_data)
    bpy.context.scene.collection.objects.link(fill)
    fill.rotation_euler = (math.radians(125), 0, math.radians(-145))


def _camera(view):
    data = bpy.data.cameras.new('sketch-camera')
    data.sensor_fit = 'HORIZONTAL'
    data.sensor_width = 36.0
    data.lens = 36.0 / (2 * math.tan(math.radians(view['hfov']) / 2))
    if view.get('clip_start'):
        data.clip_start = view['clip_start']
    camera = bpy.data.objects.new('sketch-camera', data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = view['position']
    camera.rotation_euler = (Vector(view['target']) - Vector(view['position'])).to_track_quat('-Z', 'Y').to_euler()
    scene = bpy.context.scene
    scene.camera = camera
    scene.render.resolution_x = view['width_px']
    scene.render.resolution_y = view['height_px']
    scene.render.resolution_percentage = 100


def main():
    jobs = json.loads(Path(sys.argv[sys.argv.index('--') + 1]).read_text(encoding='utf-8'))['jobs']
    for job in jobs:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        cache = {}
        for m in job['scene']['meshes']:
            _mesh(m, cache)
        _setup_render(job['scene'])
        _camera(job['scene']['view'])
        bpy.context.scene.render.filepath = job['output']
        bpy.ops.render.render(write_still=True)


if __name__ == '__main__':
    main()
