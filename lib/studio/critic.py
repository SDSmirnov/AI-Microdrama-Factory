"""
Critic — Grid Quality Gate.

Port of 05_grid_quality_gate.py using a vision-capable BaseLLM backend.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

from lib.core.schemas import PANEL_QA_SCHEMA
from lib.core.utils import DEFAULT_OUTPUT_DIR, grid_dims, load_metadata, panel_boxes
from lib.llm.base import BaseLLM

logger = logging.getLogger(__name__)

MAX_REFS_PER_PANEL = 6


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_ref_catalog(ref_dir: Path) -> Dict[str, Dict]:
    """Build catalog: { "Name": { "json": {...}, "img_path": Path, ... } }"""
    catalog: Dict[str, Dict] = {}
    if not ref_dir.exists():
        logger.warning(f"⚠️  Ref dir not found: {ref_dir}")
        return catalog

    for json_file in ref_dir.glob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        name = data.get("name", json_file.stem)
        img_path = json_file.with_suffix(".png")

        entry: Dict[str, Any] = {
            "json": data,
            "img_path": img_path if img_path.exists() else None,
            "visual_desc": data.get("visual_desc", ""),
            "video_visual_desc": data.get("video_visual_desc", ""),
            "type": data.get("type", "unknown"),
        }
        catalog[name] = entry
        norm = name.lower().replace(" ", "_").replace("-", "_")
        if norm != name:
            catalog[norm] = entry

    logger.info(f"📂 Loaded {len(set(id(v) for v in catalog.values()))} refs from {ref_dir}")
    return catalog


def find_ref(name: str, catalog: Dict[str, Dict]) -> Optional[Dict]:
    if name in catalog:
        return catalog[name]
    norm = name.lower().replace(" ", "_").replace("-", "_").replace("'", "").replace('"', "")
    if norm in catalog:
        return catalog[norm]
    title = name.replace("-", " ").replace("_", " ").title().replace(" ", "_")
    if title in catalog:
        return catalog[title]
    return None


# ---------------------------------------------------------------------------
# Grid slicing
# ---------------------------------------------------------------------------

def slice_grid(grid_path: Path, panels_count: int) -> List[Image.Image]:
    with Image.open(grid_path) as img:
        w, h = img.size
        cols, rows = grid_dims(panels_count)
        return [img.crop(box).copy() for box in panel_boxes(w, h, cols, rows, panels_count)]


# ---------------------------------------------------------------------------
# Panel analysis
# ---------------------------------------------------------------------------

def analyze_panel(
    llm: BaseLLM,
    panel_img: Image.Image,
    panel_meta: Dict,
    scene_meta: Dict,
    ref_catalog: Dict[str, Dict],
    scene_id: int,
    panel_id: int,
    threshold: int,
    prev_scene_terminal: str = None,
) -> Dict:
    ref_names = panel_meta.get("references", [])
    ref_images_content: List[Any] = []
    ref_descriptions: List[str] = []
    loaded_refs: List[str] = []

    opened_ref_imgs: List[Image.Image] = []
    for rname in ref_names[:MAX_REFS_PER_PANEL]:
        ref = find_ref(rname, ref_catalog)
        if ref and ref.get("img_path"):
            try:
                rimg = Image.open(ref["img_path"])
                opened_ref_imgs.append(rimg)
                desc = ref.get("video_visual_desc") or ref.get("visual_desc", "")
                ref_images_content.append(f'Reference "{rname}" ({ref.get("type", "?")}):\n{desc}')
                ref_images_content.append(rimg)
                ref_descriptions.append(f"- {rname}: {desc[:200]}")
                loaded_refs.append(rname)
            except Exception as e:
                logger.warning(f"  ⚠️  Could not load ref {rname}: {e}")

    visual_desc = panel_meta.get("visual_start", "") or panel_meta.get("visual_end", "")
    prev_panels = [
        {'panel_index': p['panel_index'], 'visual_desc': p['visual_end'], 'lights_and_camera': p.get('lights_and_camera', '')}
        for p in scene_meta.get('panels', [])
        if p['panel_index'] < panel_meta['panel_index']
    ]

    inter_scene_block = ""
    if panel_id == 1 and prev_scene_terminal:
        inter_scene_block = f"""
## PREVIOUS SCENE TERMINAL FRAME (cross-scene continuity check)
The previous scene ended on this visual state:
{prev_scene_terminal}
Check panel 1: does it maintain spatial continuity (location, lighting, character positions)?
If a location change or time-skip occurs, it must be stated explicitly in visual_start.
Flag in artifacts if there is an unexplained discontinuity.
"""

    prompt = f"""You are a QA supervisor for an AI film production pipeline.

## TASK
Analyze this PANEL IMAGE against its script description and character references.
Score the visual fidelity and decide if the panel needs regeneration.

## SCENE CONTEXT
Scene ID: {scene_meta.get('scene_id')}
Location: {scene_meta.get('location', 'N/A')}
Setup: {scene_meta.get('pre_action_description', '')}
Camera master: {scene_meta.get('camera_master', 'N/A')}
Lighting master: {scene_meta.get('lighting_master', 'N/A')}
{inter_scene_block}
## PREVIOUS PANELS - FOR CONTEXT AND CONSISTENCY CHECKS
<PREV_PANELS>{json.dumps(prev_panels, ensure_ascii=False, indent=2)}</PREV_PANELS>

## ANALYZED PANEL {panel_id} DESCRIPTION
Visual: {visual_desc}
Camera/Lighting: {panel_meta.get('lights_and_camera', '')}
Motion intent: {panel_meta.get('motion_prompt', '')[:300]}
Expected characters/objects: {', '.join(ref_names) if ref_names else 'None specified'}

## SCORING CRITERIA
- **fidelity** (0-10): Overall match to the description above.
- **character_consistency** (0-10): Do characters match the reference images?
  Check: face shape, hair color/style, age, build, clothing, helmet design.
  If the same character appears different from their reference, score LOW.
  Score 0 if no character references were expected for this panel.
- **composition_match** (0-10): Does the shot type, angle, framing match?
- **artifacts**: List ALL visual problems (extra limbs, wrong face, melted features,
  text overlays, wrong number of people, missing objects, etc.)
- **needs_refinement**: True if fidelity < {threshold} OR character_consistency < {threshold}
  OR critical artifacts exist.
- **refinement_prompt**: If needs_refinement, describe EXACTLY what to fix.
  Be specific: "Eckels' face does not match reference — wrong jaw shape, hair should
  be silver not brown. Helmet has circular viewport but should be fully transparent sphere."

## IMPORTANT
- Compare character faces CAREFULLY against reference images.
- Even small differences (hair color, eye color, facial structure) matter.
- A panel with beautiful composition but WRONG character face scores LOW on character_consistency.
- Panels without character references (landscapes, objects) can score 0 on character_consistency
  without needing refinement for that reason.
- Check narrative continuity

"""

    image_contents: List[Any] = []
    if ref_images_content:
        image_contents.append("# CHARACTER/OBJECT REFERENCE IMAGES\n")
        image_contents.extend(ref_images_content)
    image_contents.append(f"\n# PANEL {panel_id} TO ANALYZE\n")
    image_contents.append(panel_img)

    try:
        result = llm.analyze_image(
            image=image_contents,
            prompt=prompt,
            schema=PANEL_QA_SCHEMA,
        )
    except Exception as e:
        logger.error(f"  ❌ Gemini error scene {scene_id} panel {panel_id}: {e}")
        result = {
            "fidelity": 0,
            "character_consistency": 0,
            "composition_match": 0,
            "artifacts": [f"API_ERROR: {str(e)[:200]}"],
            "needs_refinement": True,
            "refinement_prompt": "API call failed, manual review required.",
            "reasoning": f"Error: {e}",
        }
    finally:
        for img in opened_ref_imgs:
            img.close()

    result["scene_id"] = scene_id
    result["panel_id"] = panel_id
    result["references_expected"] = ref_names
    result["references_loaded"] = loaded_refs
    return result


# ---------------------------------------------------------------------------
# Scene processing
# ---------------------------------------------------------------------------

def _load_panel_images_individual(
    output_dir: Path,
    scene_id: int,
    panels: list,
) -> Dict[int, "Image.Image"]:
    """Load individual panel PNGs from panels/ dir. Returns {panel_index: Image}."""
    panels_dir = output_dir / "panels"
    result: Dict[int, "Image.Image"] = {}
    for panel in panels:
        pid = panel["panel_index"]
        for suffix in ("_static", "_start"):
            p = panels_dir / f"{scene_id:03d}_{pid:02d}{suffix}.png"
            if p.exists():
                try:
                    result[pid] = Image.open(p)
                except Exception as e:
                    logger.warning(f"  ⚠️  Could not open {p}: {e}")
                break
    return result


def process_scene(
    llm: BaseLLM,
    scene: Dict,
    ref_catalog: Dict[str, Dict],
    grid_format: str,
    panels_per_scene: int,
    threshold: int,
    panel_filter: Optional[List[int]] = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    prev_scene_last_panel: str = None,
) -> List[Dict]:
    scene_id = scene["scene_id"]
    grid_path = output_dir / f"scene_{scene_id:03d}_grid_combined.png"
    panels = sorted(scene.get("panels", []), key=lambda p: p["panel_index"])

    if grid_path.exists():
        panel_images_list = slice_grid(grid_path, panels_per_scene)
        # index 0-based list → dict by panel_index for uniform access below
        panel_images: Dict[int, "Image.Image"] = {
            i + 1: img for i, img in enumerate(panel_images_list)
        }
    else:
        logger.warning(f"⏭️  Grid not found: {grid_path} — trying individual panel files")
        panel_images = _load_panel_images_individual(output_dir, scene_id, panels)
        if not panel_images:
            logger.warning(f"⏭️  No panel images found for scene {scene_id}, skipping")
            return []
    results = []

    for panel_meta in panels:
        pid = panel_meta["panel_index"]
        if panel_filter and pid not in panel_filter:
            continue
        if pid not in panel_images:
            logger.warning(f"  ⚠️  Panel {pid} image not available (have {sorted(panel_images)})")
            continue

        logger.info(f"  🔍 Scene {scene_id}, Panel {pid} (refs: {panel_meta.get('references', [])})")

        result = analyze_panel(
            llm=llm,
            panel_img=panel_images[pid],
            panel_meta=panel_meta,
            scene_meta=scene,
            ref_catalog=ref_catalog,
            scene_id=scene_id,
            panel_id=pid,
            threshold=threshold,
            prev_scene_terminal=prev_scene_last_panel if pid == 1 else None,
        )
        results.append(result)

        fid = result["fidelity"]
        cc = result["character_consistency"]
        need = "🔴 NEEDS FIX" if result["needs_refinement"] else "🟢 OK"
        logger.info(f"    → fidelity={fid}/10  char_consistency={cc}/10  {need}")
        if result["artifacts"]:
            for art in result["artifacts"][:3]:
                logger.info(f"       ⚠️  {art}")

    return results


# ---------------------------------------------------------------------------
# Full QA run
# ---------------------------------------------------------------------------

def run_quality_gate(
    llm: BaseLLM,
    ref_dir: Path,
    scene_ids: Optional[List[int]] = None,
    panel_ids: Optional[List[int]] = None,
    threshold: int = 5,
    max_workers: int = 10,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    output_path: Path = None,
) -> Dict:
    if output_path is None:
        output_path = output_dir / "quality_report.json"
    metadata = load_metadata(output_dir / "animation_metadata.json")  # from lib.core.utils
    ref_catalog = load_ref_catalog(ref_dir)

    config = metadata.get("config", {})
    grid_format = config.get("format", {}).get("type", "single_grid_animation")
    panels_per_scene = config.get("format", {}).get("panels_per_scene", 9)

    if not config:
        for cfg_path in [Path("custom_prompts/config.json"), Path("prompts/config.json")]:
            if cfg_path.exists():
                config = json.loads(cfg_path.read_text(encoding="utf-8"))
                grid_format = config.get("format", {}).get("type", grid_format)
                panels_per_scene = config.get("format", {}).get("panels_per_scene", panels_per_scene)
                break

    all_scenes = metadata.get("scenes", [])

    # Build terminal-frame map for inter-scene continuity checks at panel 1
    all_scenes_sorted = sorted(all_scenes, key=lambda s: s.get("scene_id", 0))
    sorted_scene_ids = [s["scene_id"] for s in all_scenes_sorted]
    terminal_frame_map: Dict[int, str] = {}
    for s in all_scenes_sorted:
        panels = sorted(s.get("panels", []), key=lambda p: p.get("panel_index", 0))
        if panels:
            terminal_frame_map[s["scene_id"]] = panels[-1].get("visual_end", "")

    def _prev_terminal(scene_id: int) -> Optional[str]:
        idx = sorted_scene_ids.index(scene_id) if scene_id in sorted_scene_ids else -1
        if idx > 0:
            return terminal_frame_map.get(sorted_scene_ids[idx - 1])
        return None

    scenes = all_scenes if not scene_ids else [s for s in all_scenes if s["scene_id"] in scene_ids]

    all_results: List[Dict] = []
    if max_workers > 1 and len(scenes) > 1 and not panel_ids:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    process_scene, llm, scene, ref_catalog, grid_format,
                    panels_per_scene, threshold, None, output_dir,
                    _prev_terminal(scene["scene_id"]),
                ): scene["scene_id"]
                for scene in scenes
            }
            for future in as_completed(futures):
                sid = futures[future]
                try:
                    all_results.extend(future.result())
                except Exception as e:
                    logger.error(f"❌ Scene {sid} error: {e}")
    else:
        for scene in scenes:
            all_results.extend(
                process_scene(llm, scene, ref_catalog, grid_format, panels_per_scene,
                               threshold, panel_ids, output_dir, _prev_terminal(scene["scene_id"]))
            )

    all_results.sort(key=lambda r: (r["scene_id"], r["panel_id"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Upsert: preserve results for scenes/panels not touched by this run
    if output_path.exists() and (scene_ids or panel_ids):
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            kept = existing.get("panels", [])
        except Exception:
            kept = []

        # Build lookup of newly scanned (scene_id, panel_id) keys
        scanned_keys = {(r["scene_id"], r["panel_id"]) for r in all_results}
        kept = [p for p in kept if (p["scene_id"], p["panel_id"]) not in scanned_keys]
        all_results = sorted(kept + all_results, key=lambda r: (r["scene_id"], r["panel_id"]))

    report = {
        "threshold": threshold,
        "total_panels": len(all_results),
        "needs_refinement": sum(1 for r in all_results if r["needs_refinement"]),
        "avg_fidelity": round(sum(r["fidelity"] for r in all_results) / max(len(all_results), 1), 2),
        "panels": all_results,
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.info(f"📄 Report saved: {output_path}")
    return report


def print_summary(report: Dict, threshold: int):
    results = report.get("panels", [])
    if not results:
        logger.info("No results to display.")
        return

    total = len(results)
    needs_fix = sum(1 for r in results if r["needs_refinement"])
    avg_fid = report.get("avg_fidelity", 0)

    print(f"\n{'=' * 72}")
    print(f"{'QUALITY GATE REPORT':^72}")
    print(f"{'=' * 72}")
    print(f"  Panels analyzed:      {total}")
    print(f"  Average fidelity:     {avg_fid:.1f}/10")
    print(f"  Threshold:            {threshold}")
    print(f"  🟢 Passed:            {total - needs_fix}")
    print(f"  🔴 Needs refinement:  {needs_fix}")
    print(f"{'=' * 72}\n")
