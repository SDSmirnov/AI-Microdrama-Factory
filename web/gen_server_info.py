#!/usr/bin/env python3
"""Generate web/server-info.json for the development web viewer.
Run via: python3 web/gen_server_info.py  (from project root)
"""
import json, os, re

cr = 'cinematic_render'

novels = sorted(f for f in os.listdir('.') if re.match(r's\d+e\d+\.txt', f))

scene_files = []
for i in range(1, 31):
    n = str(i).zfill(3)
    has_refined = os.path.exists(f'{cr}/animation_episode_scenes_{n}_refined.json')
    has_raw     = os.path.exists(f'{cr}/animation_episode_scenes_{n}.json')
    if has_refined or has_raw:
        scene_files.append({'episode': i, 'has_refined': has_refined, 'has_raw': has_raw})

sb: dict[int, dict] = {}
for f in (os.listdir(cr) if os.path.isdir(cr) else []):
    m = re.match(r'scene_(\d{3})_grid_combined\.png$', f)
    if m:
        sb.setdefault(int(m.group(1)), {})['current'] = f'{cr}/{f}'
        continue
    m = re.match(r'scene_(\d{3})_grid_combined_backup.*\.png$', f)
    if m:
        sid = int(m.group(1))
        sb.setdefault(sid, {}).setdefault('backups', []).append(f'{cr}/{f}')

storyboards = []
for sid in sorted(sb):
    entry: dict = {'scene': sid}
    if 'current' in sb[sid]:
        entry['current'] = sb[sid]['current']
    backups = sorted(sb[sid].get('backups', []))
    if backups:
        entry['backups'] = backups
    storyboards.append(entry)

info = {
    'novels':       novels,
    'scene_files':  scene_files,
    'has_metadata': os.path.exists(f'{cr}/animation_metadata.json'),
    'storyboards':  storyboards,
}

os.makedirs('web', exist_ok=True)
with open('web/server-info.json', 'w') as fh:
    json.dump(info, fh, indent=2)
print('web/server-info.json written')
