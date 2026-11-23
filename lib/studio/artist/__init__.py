"""Artist: references, room views, storyboard rendering. Re-exports every submodule name."""
from lib.studio.artist.view_catalog import (
    _MULTIPANEL_MARKERS,
    _Y_AXIS_VIEWS,
    _X_AXIS_VIEWS,
    _OUTDOOR_VIEW_SUFFIXES,
    _VIEW_RENDER_CONSISTENCY,
    _VIEW_CAMERA_PHRASES,
    _view_logline,
    _ROOM_VIEWS,
    _VEHICLE_VIEWS,
    _OUTDOOR_VIEWS,
    _truth_ref_suffixes,
    _ensure_view_metadata,
)
from lib.studio.artist.view_geometry import (
    _parse_room_dims,
    _SUPPORTED_IMAGE_ASPECTS,
    _nearest_supported_aspect,
    _room_view_aspect_ratio,
    _view_aspect_ratio,
    _VIEW_CAMERA,
    _is_wall_camera,
    _project_image_x,
    _VIEW_POSITION_LABEL,
    _VIEW_FACING_WALL,
    _VIEW_HFOV,
    _FIT_HFOV_RANGE,
    _FIT_MARGIN,
    NATURAL_HFOV,
    MAX_SETBACK_M,
    _view_rig,
    _view_hfov,
    view_camera,
    OUTDOOR_ASPECT,
    _OUTDOOR_HFOV,
)
from lib.studio.artist.anchor_prompt import (
    _anchor_id,
    _anchor_title,
    _extract_camera_anchor_labels,
    _anchor_visibility_block,
    _load_entrance_anchor_points,
)
from lib.studio.artist.render_utils import (
    _run_render_tasks,
    _load_scenes,
    _ref_label,
    known_refs,
)
from lib.studio.artist.catalog import (
    load_character_refs,
    generate_single_reference,
    _existing_refs_context,
    _enrich_refs_pass,
    auto_cast_characters,
)
from lib.studio.artist.ref_render import (
    _render_single_ref,
    _topo_sort_refs,
    render_character_refs,
)
from lib.studio.artist.room_views import (
    _qa_and_refine_room_view,
    remake_room_refs,
    _VIEW_DESC_SCHEMA,
    _extract_view_desc,
)
from lib.studio.artist.room_anchors import (
    _generate_room_anchors,
    _generate_outdoor_anchors,
    _current_image,
    run_room_anchors,
)
from lib.studio.artist.room_detail import (
    _build_vocabulary_prompt,
    _build_view_prompt,
    _ARCHITECTURE_RULE,
    _build_vocabulary_critique_prompt,
    _build_view_critique_prompt,
    _critique_vocabulary,
    _missing_ids,
    _ascii_ids,
    _section,
    _critique_view,
    detail_room_refs,
)
from lib.studio.artist.grids import (
    _grid_layout_spec,
    _build_prompt_header,
    _build_grid_prompt,
    _MAX_GRID_RETRIES,
    _quick_grid_check,
    _render_single_grid,
    render_scene_grids,
    slice_combined,
)
from lib.studio.artist.panels import (
    panel_anchor_block_enabled,
    _panel_camera_xy,
    _panel_anchor_context,
    _panel_blocking_context,
    _with_sketch,
    SKETCH_LABEL,
    _build_panel_prompt,
    _build_ref_contents,
    _panel_image_size,
    _panel_output_path,
    _render_single_panel,
    render_panels,
    render_extra_panel,
)
from lib.studio.artist.fullframe import (
    _derive_fullframe_disposition,
    _derive_fullframe_visual,
    _build_fullframe_prompt,
    render_full_frame_panel,
)
from lib.studio.artist.image_prompt import (
    _build_image_prompt,
    export_image_prompt,
)
