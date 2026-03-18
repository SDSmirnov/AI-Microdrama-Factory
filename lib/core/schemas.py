"""
All JSON schemas used across the pipeline, consolidated in one place.
"""
import os

_LANG = os.getenv("TARGET_LANGUAGE", "Russian")

SCREENPLAY_SCHEMA = {
    "type": "object",
    "properties": {
        "logline": {"type": "string"},
        "title": {"type": "string"},
        "characters": {"type": "array", "items": {"type": "string"}},
        "nitpicker_report": {"type": "string"},
        "shit_redo_report": {"type": "string"},
        "episodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "episode_id": {"type": "integer"},
                    "chapter_id": {"type": "integer", "description": "Source chapter number (1-based). All three sub-episodes of the same chapter share the same chapter_id. Transition episodes use 0."},
                    "episode_type": {"type": "string", "description": "Structural role — use values defined by the active style. Multi-POV styles: pov_a (first protagonist only), pov_b (second protagonist only), confrontation (both characters), transition (time-gap bridge). Long-arc styles: arc_open (first episode of arc unit), arc_mid (middle episode), arc_close (final episode of arc unit), transition (bridge between arc units)."},
                    "pov_character": {"type": "string", "description": "Name of the POV character for pov_a/pov_b episodes. Empty string for all other episode types."},
                    "location": {"type": "string"},
                    "daytime": {"type": "string"},
                    "raw_narrative": {"type": "string", "description": "Full narative from the original text which was used for this episode, do not shorted used text, it will be used for the context"},
                    "visual_continuity_rules": {"type": "string", "description": "Visual continunity enforcement for the next episode to avoid discrepancies throughout the movie. Never tell 'same', instead pass full details for the visual state."},
                    "screenplay_instructions": {"type": "string", "description": "Very detailed instructions"},
                },
                "required": ["episode_id", "chapter_id", "episode_type", "pov_character", "location", "daytime", "raw_narrative", "screenplay_instructions", "visual_continuity_rules"],
            }
        }
    },
    "required": ["logline", "title", "characters", "episodes", "nitpicker_report"],
}

SCENE_SCHEMA = {
    "type": "object",
    "properties": {
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scene_id": {"type": "integer"},
                    "location": {"type": "string"},
                    "pre_action_description": {"type": "string"},
                    "camera_master": {"type": "string", "description": "Master camera setup for the entire scene: dominant lens (mm), angle, primary lighting condition. All panels share this baseline — explicit deviations stated in lights_and_camera."},
                    "lighting_master": {"type": "string", "description": "Master lighting blueprint for the scene: key light direction/color/quality, fill ratio, visible practicals. All panels inherit this lighting DNA."},
                    "panels": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "panel_index": {"type": "integer"},
                                "visual_start": {"type": "string"},
                                "visual_end": {"type": "string"},
                                "motion_prompt": {"type": "string"},
                                "is_reversed": {"type": "boolean", "description": "True if this panel's action must be revealed in reverse chronological order (e.g. fog clears to reveal a character, door opens and character comes in, charater looks in the window and then turns his face to camera etc). When true, visual_start describes the OBSCURED/FINAL state seen first by the viewer, and visual_end describes the REVEALED/ORIGIN state seen last."},
                                "motion_prompt_reversed": {"type": "string", "description": "Populated ONLY when is_reversed is true. Describes the reversed playback motion: how the scene should visually transition from visual_start (obscured) to visual_end (revealed) as perceived by the viewer. Empty string when is_reversed is false."},
                                "lights_and_camera": {"type": "string"},
                                "dialogue": {"type": "string", "description": f"Dialogue line, in {_LANG}, add names and male/female indicators. E.g. 'Alice (old female): What a lovely cityscape here'. David (male kid): I know."},
                                "voiceover": {"type": "string", "description": f"Off-screen narration / inner monologue in {_LANG} synced to panel action. Reveals subtext — what the viewer CANNOT see (fear, memory, desire). Never describes what is visually obvious. Add Male/Female voice indicator. Voiceover must not overlap dialogs. Use timestamps if needed, e.g. 'at 2.0s mark, after Alice finishes her line, Male Voiceover: Damn it!'"},
                                "emotional_beat": {"type": "string", "description": "Dominant emotion of this panel (single word): tension, revelation, grief, desire, defiance, dread, relief, rage, longing, shock, shame, triumph"},
                                "hook_type": {"type": "string", "description": "Role of this panel in episode dramaturgy: cold_open | verbal_hook | escalation | emotional_capture | confrontation | twist | cliffhanger | arc_bridge | arc_pickup | backlink | none. cold_open and cliffhanger support subtypes via slash: cold_open/status_reversal | cold_open/impossible_situation | cold_open/hidden_identity | cold_open/ticking_clock | cold_open/revelation; cliffhanger/physical_threat | cliffhanger/revelation | cliffhanger/emotional_rupture | cliffhanger/interrupted_action. Use verbal_hook for panel 2 (≈7s, spoken conflict statement). Use emotional_capture for panel 4 (≈21s, point of no return)."},
                                "text_safe_composition": {"type": "boolean", "description": "True when key subjects (faces, hands, action) are composed in the middle 65% of frame height, leaving top 15% and bottom 20% clear for subtitle overlays."},
                                "panel_type": {"type": "string", "description": "Always 'narrative'. Every panel shows characters in action — no faceless atmosphere-only shots."},
                                "transition_to_next": {"type": "string", "description": "Edit cut technique to the next panel: match_cut (cut on matching shape/motion — visual_end of this panel mirrors visual_start of next), jump_cut (jarring deliberate cut for pace — allows duration 2–3s), smash_cut (sudden silence-to-action or reverse), j_cut (next panel audio begins audibly in the final 1–2s of this panel — note in sound_design), hard_cut (standard clean cut, default)."},
                                "sound_design": {"type": "string", "description": "Sonic atmosphere cue for this panel, independent of dialogue/voiceover. Required for every panel. E.g.: 'silence', 'ambient hum', 'pin-drop silence building to heartbeat at 5s', 'bass drop on cut', 'amplified footstep at 2s', 'J-cut: rain ambient from next scene starts at 5s', 'glass crack at 4s then silence'."},
                                "caption": {"type": "string"},
                                "duration": {"type": "integer"},
                                "references": {"type": "array", "items": {"type": "string"}},
                                "location_references": {"type": "array", "items": {"type": "string"}, "description": "Location/environment reference names visible in this panel. Use the specific view ref that matches the camera angle: for rooms use '{Room-Name}-View-From-Entrance' (camera at door looking in) or '{Room-Name}-View-To-Entrance' (camera at far end looking toward door); for vehicles use '{Vehicle-Name}-Exterior', '{Vehicle-Name}-Interior-From-Entrance', or '{Vehicle-Name}-Interior-To-Entrance'. Names must exactly match existing refs or rendering will skip them."},
                            },
                            "required": ["panel_index", "visual_start", "visual_end", "motion_prompt", "is_reversed", "motion_prompt_reversed", "lights_and_camera", "dialogue", "voiceover", "emotional_beat", "hook_type", "text_safe_composition", "panel_type", "transition_to_next", "sound_design", "caption", "duration", "references", "location_references"]
                        }
                    }
                },
                "required": ["scene_id", "location", "panels"]
            }
        }
    },
    "required": ["scenes"]
}

CHARACTER_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the reference. Avoid punctuation, quotes and parenthesis, use only letters, digits and hyphens."},
            "logline_subject_info": {"type": "string", "description": "One-sentence semantic description of who/what this is in the story (role, relationship, function). Used to deduplicate refs across runs — must be unique enough to distinguish from similarly-named entities."},
            "visual_desc": {"type": "string", "description": "verbose detailed description for the reference image generation"},
            "type": {"type": "string", "description": "Character, location, object, interface, room, vehicle"},
            "video_visual_desc": {"type": "string", "description": "Concise visual description for scene context injection. Must preserve: physical build, clothing, face, and — for characters — ALL carry items (bag type and placement, holster location, wallet pocket, keys, badge). Omitting carry items causes actors to pull weapons/phones from thin air in generated scenes."},
            "style_reference": {"type": "string", "description": "Name of the existing or new reference, for details consistency. E.g. for view to entrance, use view from entrance."},
        },
        "required": ["name", "logline_subject_info", "visual_desc", "type", "style_reference", "video_visual_desc"]
    }
}

ENRICHMENT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Exact name matching an existing reference (letters, digits, hyphens only)."},
            "visual_desc_additions": {"type": "string", "description": "Specific visual details found in the text that are NOT yet in the existing description. Props, materials, colors, spatial arrangement, textures, inscriptions, etc. Empty string if nothing new found."},
        },
        "required": ["name", "visual_desc_additions"]
    }
}

REVERSAL_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "panel_index": {"type": "integer"},
            "motion_prompt_reversed": {"type": "string"}
        },
        "required": ["panel_index", "motion_prompt_reversed"]
    }
}

PANEL_QA_SCHEMA = {
    "type": "object",
    "properties": {
        "fidelity": {
            "type": "integer",
            "description": (
                "Overall visual fidelity score 0-10. "
                "10 = perfect match to references and description. "
                "0 = completely wrong."
            ),
        },
        "character_consistency": {
            "type": "integer",
            "description": (
                "How well characters match their reference images 0-10. "
                "Evaluate face, hair, build, clothing, helmet design. "
                "0 if no characters expected. 10 = identical to reference."
            ),
        },
        "composition_match": {
            "type": "integer",
            "description": (
                "How well the panel matches the requested shot type, "
                "camera angle, and framing 0-10."
            ),
        },
        "dramatic_intensity": {
            "type": "integer",
            "description": (
                "How dramatically engaging is this panel 0-10. "
                "10 = maximum tension, conflict, or emotional shock — viewer cannot look away. "
                "0 = static, generic, no visible conflict or hook. "
                "A technically perfect but inert panel (no conflict, generic pose, no tension) scores 0. "
                "Score as if this frame had to stop a scrolling thumb in 0.3 seconds."
            ),
        },
        "artifacts": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "List of specific visual artifacts or errors found: "
                "extra fingers, melted faces, wrong number of people, "
                "text/watermarks, broken geometry, etc."
            ),
        },
        "needs_refinement": {
            "type": "boolean",
            "description": (
                "True if the panel should be regenerated or refined. "
                "Triggers when: fidelity is below threshold, character_consistency is below threshold, "
                "dramatic_intensity is below threshold (panel is technically correct but dramatically inert), "
                "or critical visual artifacts exist."
            ),
        },
        "refinement_prompt": {
            "type": "string",
            "description": (
                "If needs_refinement is true: a precise prompt describing "
                "WHAT to fix. Reference specific issues. "
                "If false: empty string."
            ),
        },
        "suggest_mirror": {
            "type": "boolean",
            "description": (
                "True if the ONLY spatial fix needed is horizontally flipping this panel. "
                "Set when character/object positions are mirrored vs previous panels "
                "but faces, lighting, and composition are otherwise acceptable. "
                "Must also set needs_refinement=true when this is true."
            ),
        },
        "mirror_reason": {
            "type": "string",
            "description": (
                "If suggest_mirror is true: describe which character or element is spatially "
                "flipped and relative to which panel. Empty string otherwise."
            ),
        },
        "reasoning": {
            "type": "string",
            "description": "Brief explanation of the scores.",
        },
    },
    "required": [
        "fidelity",
        "character_consistency",
        "composition_match",
        "artifacts",
        "needs_refinement",
        "refinement_prompt",
        "suggest_mirror",
        "mirror_reason",
        "dramatic_intensity",
        "reasoning",
    ],
}

GRID_QA_SCHEMA = {
    "type": "object",
    "properties": {
        "passed": {
            "type": "boolean",
            "description": (
                "True if the grid is worth keeping for downstream QA refinement. "
                "False ONLY if the grid is fundamentally unusable: completely blank or corrupted image, "
                "wrong number of panels in the grid, "
                "entirely wrong scene/setting with no resemblance to references, "
                "or so many simultaneous catastrophic failures that refinement cannot recover it. "
                "Character drift, minor identity mismatch, wrong lighting, missing props — "
                "these are NOT grounds for failure; QA refinement handles them. "
                "When in doubt, pass=true."
            ),
        },
        "reason": {
            "type": "string",
            "description": "If passed=false: specific description of what is fundamentally broken. If passed=true: empty string.",
        },
    },
    "required": ["passed", "reason"],
}

UPDATED_REF_SCHEMA = {
    "type": "object",
    "properties": {
        "visual_desc": {"type": "string", "description": "Highly detailed, comprehensive visual description incorporating all new scene details."},
        "video_visual_desc": {"type": "string", "description": "Concise updated description for scene context injection. Must preserve all carry items (bag, holster, pockets, badge) — these are referenced when characters retrieve objects in panels."}
    },
    "required": ["visual_desc", "video_visual_desc"]
}

ANCHOR_SCHEMA = {
    "type": "object",
    "properties": {
        "axes": {
            "type": "string",
            "description": (
                "Coordinate system definition. Example: "
                "'Origin (0,0) = entrance door center at floor level. "
                "X positive = East (right when entering). "
                "Y positive = South (into room, away from entrance). "
                "Z positive = up. "
                "NOTE: View-To-Entrance mirrors all X coordinates (left↔right swap).'"
            ),
        },
        "room_m": {
            "type": "array",
            "items": {"type": "number"},
            "description": "[width_x, depth_y] in meters",
        },
        "objects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "kebab-case identifier, e.g. 'marble-table-south'"},
                    "label": {"type": "string"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                    "notes": {"type": "string", "description": "Seating sides, orientation, structural notes"},
                },
                "required": ["id", "label", "x", "y", "z"],
            },
        },
        "zones": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "kebab-case zone id, e.g. 'bar-area'"},
                    "label": {"type": "string"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "visual_disposition_hint": {
                        "type": "string",
                        "description": (
                            "Natural-language anchor phrase for visual_disposition panel field. "
                            "Must NOT use coordinates. Use landmark references instead. "
                            "Example: 'seated on the left side of the marble table, back to the brick wall, "
                            "gilded mirror centered behind'. Must be copy-pasteable into a panel prompt."
                        ),
                    },
                },
                "required": ["id", "label", "x", "y", "visual_disposition_hint"],
            },
        },
    },
    "required": ["axes", "room_m", "objects", "zones"],
}

SCENE_REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "panels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "panel_index": {"type": "integer"},
                    "visual_start": {"type": "string"},
                    "visual_end": {"type": "string"},
                    "lights_and_camera": {"type": "string", "description": "Camera/lighting corrected to match scene camera_master and lighting_master. Copy original value verbatim if no correction needed."}
                },
                "required": ["panel_index", "visual_start", "visual_end", "lights_and_camera"]
            }
        }
    },
    "required": ["panels"]
}
