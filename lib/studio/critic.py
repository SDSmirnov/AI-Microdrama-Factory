"""
Critic — Grid Quality Gate.

Port of 05_grid_quality_gate.py using a vision-capable BaseLLM backend.
"""
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

from lib.core.schemas import PANEL_QA_SCHEMA
from lib.llm.base import BaseLLM

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("cinematic_render")
META_FILE = OUTPUT_DIR / "animation_metadata.json"
REPORT_FILE = OUTPUT_DIR / "quality_report.json"

MAX_REFS_PER_PANEL = 6


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_metadata(meta_path: Path = META_FILE) -> Dict:
    if not meta_path.exists():
        logger.error(f"❌ Metadata not found: {meta_path}")
        sys.exit(1)
    return json.loads(meta_path.read_text(encoding="utf-8"))


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
    img = Image.open(grid_path)
    w, h = img.size

    if panels_count == 9:
        cols, rows = 3, 3
    elif panels_count == 6:
        cols, rows = 3, 2
    elif panels_count == 4:
        cols, rows = 2, 2
    else:
        cols = 3
        rows = (panels_count + 2) // 3

    pw, ph = w // cols, h // rows
    panels = []
    for r in range(rows):
        for c in range(cols):
            if len(panels) >= panels_count:
                break
            box = (c * pw, r * ph, (c + 1) * pw, (r + 1) * ph)
            panels.append(img.crop(box))
    return panels


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
) -> Dict:
    ref_names = panel_meta.get("references", [])
    ref_images_content: List[Any] = []
    ref_descriptions: List[str] = []
    loaded_refs: List[str] = []

    for rname in ref_names[:MAX_REFS_PER_PANEL]:
        ref = find_ref(rname, ref_catalog)
        if ref and ref.get("img_path"):
            try:
                rimg = Image.open(ref["img_path"])
                desc = ref.get("video_visual_desc") or ref.get("visual_desc", "")
                ref_images_content.append(f'Reference "{rname}" ({ref.get("type", "?")}):\n{desc}')
                ref_images_content.append(rimg)
                ref_descriptions.append(f"- {rname}: {desc[:200]}")
                loaded_refs.append(rname)
            except Exception as e:
                logger.warning(f"  ⚠️  Could not load ref {rname}: {e}")

    visual_desc = panel_meta.get("visual_start", "") or panel_meta.get("visual_end", "")
    prev_panels = [
        {'panel_index': p['panel_index'], 'visual_desc': p['visual_end']}
        for p in scene_meta.get('panels', [])
        if p['panel_index'] < panel_meta['panel_index']
    ]

    prompt = f"""You are a QA supervisor for an AI film production pipeline.

## TASK
Analyze this PANEL IMAGE against its script description and character references.
Score the visual fidelity and decide if the panel needs regeneration.

## SCENE CONTEXT
Scene ID: {scene_meta.get('scene_id')}
Location: {scene_meta.get('location', 'N/A')}
Setup: {scene_meta.get('pre_action_description', '')}

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

    contents: List[Any] = []
    if ref_images_content:
        contents.append("# CHARACTER/OBJECT REFERENCE IMAGES\n")
        contents.extend(ref_images_content)
    contents.append(f"\n# PANEL {panel_id} TO ANALYZE\n")
    contents.append(panel_img)
    contents.append(prompt)

    try:
        result = llm.analyze_image(
            image=contents[:-1],  # everything except prompt
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

    result["scene_id"] = scene_id
    result["panel_id"] = panel_id
    result["references_expected"] = ref_names
    result["references_loaded"] = loaded_refs
    return result


# ---------------------------------------------------------------------------
# Scene processing
# ---------------------------------------------------------------------------

def process_scene(
    llm: BaseLLM,
    scene: Dict,
    ref_catalog: Dict[str, Dict],
    grid_format: str,
    panels_per_scene: int,
    threshold: int,
    panel_filter: Optional[List[int]] = None,
) -> List[Dict]:
    scene_id = scene["scene_id"]
    grid_path = OUTPUT_DIR / f"scene_{scene_id:03d}_grid_combined.png"
    if not grid_path.exists():
        logger.warning(f"⏭️  Grid not found: {grid_path}")
        return []

    panel_images = slice_grid(grid_path, panels_per_scene)
    panels = sorted(scene.get("panels", []), key=lambda p: p["panel_index"])
    results = []

    for panel_meta in panels:
        pid = panel_meta["panel_index"]
        if panel_filter and pid not in panel_filter:
            continue
        if pid < 1 or pid > len(panel_images):
            logger.warning(f"  ⚠️  Panel {pid} out of range (have {len(panel_images)} images)")
            continue

        logger.info(f"  🔍 Scene {scene_id}, Panel {pid} (refs: {panel_meta.get('references', [])})")

        result = analyze_panel(
            llm=llm,
            panel_img=panel_images[pid - 1],
            panel_meta=panel_meta,
            scene_meta=scene,
            ref_catalog=ref_catalog,
            scene_id=scene_id,
            panel_id=pid,
            threshold=threshold,
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
    max_workers: int = 20,
    output_path: Path = REPORT_FILE,
) -> Dict:
    metadata = load_metadata()
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

    scenes = metadata.get("scenes", [])
    if scene_ids:
        scenes = [s for s in scenes if s["scene_id"] in scene_ids]

    all_results: List[Dict] = []
    if max_workers > 1 and len(scenes) > 1 and not panel_ids:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(process_scene, llm, scene, ref_catalog, grid_format,
                                panels_per_scene, threshold, None): scene["scene_id"]
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
                               threshold, panel_ids)
            )

    all_results.sort(key=lambda r: (r["scene_id"], r["panel_id"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)

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
