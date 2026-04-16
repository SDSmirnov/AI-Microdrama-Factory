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
                    "chapter_id": {"type": "integer", "description": "Source chapter number (1-based). Transition episodes use 0."},
                    "episode_type": {"type": "string", "description": "Structural role — use values defined by the active style. Generic/microdrama styles: standard (default), pov (single protagonist's perspective, set pov_character), transition (time/location bridge). Long-arc styles: arc_open, arc_mid, arc_close, transition."},
                    "pov_character": {"type": "string", "description": "Name of the character whose perspective this episode follows. Required for pov episode type. Empty string for standard, transition, arc_open, arc_mid, arc_close."},
                    "location": {"type": "string"},
                    "daytime": {"type": "string"},
                    "raw_narrative": {"type": "string", "description": "Full narative from the original text which was used for this episode, do not shorted used text, it will be used for the context"},
                    "rewritten_condensed_narrative": {"type": "string", "description": "The episode source text rewritten as a tight, unbroken dramatic script: every spoken line verbatim, every physical beat in chronological sequence, no narrative ellipses or author commentary. This is the dialogue and action coverage contract — every line and beat present here MUST appear in the generated panels. Scene generation must not drop any line. LANGUAGE: must be written in the SAME language as the source text — do NOT translate. Translation causes semantic drift when panels are later generated back into the original language."},
                    "visual_continuity_rules": {"type": "string", "description": "Continuity block injected verbatim into the next episode's scene generator as a mandatory constraint. Format and required sections are defined by the active style's screenplay_episodes prompt. Never use 'same as before' — always write explicit imperatives with full state details."},
                    "active_questions": {
                        "type": "object",
                        "description": "Open dramatic questions ledger. Maintains the curiosity fuel that keeps viewers engaged. At least one question must remain open at episode end. Macro question must not be answered until the final episode.",
                        "properties": {
                            "macro": {"type": "string", "description": "The series-long dramatic question driving the whole story. Unchanged throughout all episodes. E.g. 'Will Alisa escape with the evidence before Pavel destroys it and her?'"},
                            "episode": {"type": "string", "description": "The question this episode raises or escalates. E.g. 'Will she sign tonight or find a way out?'"},
                            "scene": {"type": "string", "description": "The immediate question keeping the viewer watching this episode. E.g. 'Does he know she is stalling, or is he still blind to it?'"},
                            "planted_this_episode": {"type": "string", "description": "New question seeded this episode for future payoff within 3 episodes. Empty string if none. E.g. 'Why did she pocket her phone without looking at it?'"},
                            "answered_this_episode": {"type": "string", "description": "Question from a prior episode answered here. 'none' if not applicable."}
                        },
                        "required": ["macro", "episode", "scene", "planted_this_episode", "answered_this_episode"],
                        "additionalProperties": False
                    },
                    "screenplay_instructions": {"type": "string", "description": "DEPRECATED — kept for backward compatibility with old episode files. Use scenes[].scene_instructions instead."},
                    "scenes": {
                        "type": "array",
                        "description": "Scene breakdown for this episode. Each episode has 1–3 scenes; each scene is a single location/action unit with its own panel count decided by the screenwriter based on pacing.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "scene_local_id": {"type": "integer", "description": "1-based scene index within this episode."},
                                "location": {"type": "string"},
                                "panel_count": {
                                    "type": "integer",
                                    "description": "Number of panels for this scene. Must be one of: 4, 6, 9, 10, 12. Choose based on pacing: 4–6 = travel/smalltalk/gap bridge, 9 = standard confrontation or full dramatic arc, 10–12 = high-density dialogue peak or climactic scene."
                                },
                                "scene_instructions": {
                                    "type": "string",
                                    "description": "Per-panel production blueprint for this scene, P1 through PN (N = panel_count). Structured text following the format defined in the active style's screenplay_episodes prompt — do not invent format; use exactly what the prompt specifies. Used verbatim by the scene generator to produce panel keyframes."
                                },
                                "initial_disposition": {
                                    "type": "string",
                                    "description": "Spatial baseline for this scene's opening frame. Written in natural language — no anchor IDs required. Lists every character present at scene open: position relative to room landmarks (walls, doors, windows, furniture), facing direction, spatial relation to other characters. Example: 'Jack is on the sofa at the East wall facing the TV on the West wall. Jane is seated beside him on his right (North side). Joe stands near the kitchen doorway, hand on the door handle, about to enter.' The disposition pass resolves this to anchor zone IDs for P1. Leave empty string for transition episodes."
                                },
                                "background_activity": {
                                    "type": "object",
                                    "description": (
                                        "Background crowd/NPC life. REQUIRED for every scene — the LLM must make an explicit decision. "
                                        "Set density='none' for private/empty locations (apartment, interrogation room, abandoned warehouse, after-hours office). "
                                        "Set density to any other value for public/semi-public locations (bank office, café, restaurant, street, waiting room). "
                                        "When density≠'none': Pass 2 renders background figures in MS/WS panels; Pass 3 adds ambient motion layer."
                                    ),
                                    "properties": {
                                        "crowd_type": {
                                            "type": "string",
                                            "description": "Who populates the background. Empty string when density='none'. E.g. 'bank clerks at teller windows and customers filling out forms', 'café patrons at nearby tables, a waitress refilling coffee'."
                                        },
                                        "density": {
                                            "type": "string",
                                            "enum": ["none", "sparse", "moderate", "busy", "crowded"],
                                            "description": "none=private/empty location (no background extras); sparse=1–2 extras visible; moderate=3–5; busy=active crowd; crowded=packed."
                                        },
                                        "movement": {
                                            "type": "string",
                                            "description": "Ambient motion for Pass 3 motion_prompts. Empty string when density='none'. E.g. 'slow drift between counters, occasional document exchange, muted conversation'."
                                        },
                                        "focal_plane": {
                                            "type": "string",
                                            "description": "Depth and focus hint for Pass 2. Empty string when density='none'. E.g. 'mid-to-far ground, soft focus'."
                                        }
                                    },
                                    "required": ["crowd_type", "density", "movement", "focal_plane"],
                                    "additionalProperties": False
                                },
                            },
                            "required": ["scene_local_id", "location", "panel_count", "scene_instructions", "background_activity"],
                            "additionalProperties": False
                        }
                    },
                },
                "required": ["episode_id", "chapter_id", "episode_type", "pov_character", "location", "daytime", "raw_narrative", "rewritten_condensed_narrative", "scenes", "visual_continuity_rules", "active_questions"],
                "additionalProperties": False
            }
        }
    },
    "required": ["logline", "title", "characters", "episodes", "nitpicker_report"],
    "additionalProperties": False
}

PANEL_STATE_SCHEMA = {
  "description": "State-driven panel architecture where motion_action is localized to actors and props.",
  "type": "object",
  "properties": {
    "actors": {
      "type": "array",
      "description": "Full roster of actors. Every actor present in the scene must be listed, regardless of in_frame status.",
      "items": {
        "type": "object",
        "properties": {
          "name": { "type": "string" },
          "position": {
            "type": "string",
            "description": "Relative to location anchors (e.g., 'by the door') and/or other actors (e.g., '3ft behind Joe')."
          },
          "pose": { "type": "string" },
          "gaze_target": { "type": ["string", "null"] },
          "chest_direction": { "type": "string" },
          "head_direction": { "type": "string" },
          "motion_action": {
            "type": "string",
            "description": "The high-level action performed by this actor during this panel (e.g., 'Walks in')."
          },
          "in_frame": { "type": "boolean" },
          "vehicle_position": {
            "type": ["string", "null"],
            "description": (
                "Exact seat or position inside/outside a vehicle. "
                "Required when the scene is set inside or immediately adjacent to a vehicle; null otherwise. "
                "Use unambiguous seat labels: 'driver seat', 'front passenger seat', "
                "'rear left seat (behind driver)', 'rear right seat (behind front passenger)', "
                "'rear center seat', 'cargo area', "
                "'at the driver door (outside)', 'at the front passenger door (outside)', "
                "'at the rear left door (outside)', 'at the rear right door (outside)', "
                "'on the hood', 'on the roof', 'in the trunk'. "
                "Do NOT use compass directions or vague terms like 'back seat'."
            )
          },
          "visual_ref": {
            "type": "string",
            "description": (
                "Ref slug to use for this actor in this panel. "
                "Use the base character name when no variation applies. "
                "Use a variation slug (e.g. 'Alisa-Gown') when a costume/context variant exists and applies. "
                "Must match an existing ref slug exactly (letters, digits, hyphens)."
            )
          }
        },
        "required": ["name", "position", "pose", "chest_direction", "motion_action", "in_frame", "gaze_target", "visual_ref"],
        "additionalProperties": False
      }
    },
    "props": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": { "type": "string" },
          "position": { "type": "string" },
          "prop_change": {
            "type": "string",
            "description": "Physical or state transformation of the object (e.g., 'empty after Jack poured wine')."
          }
        },
        "required": ["name", "position", "prop_change"],
        "additionalProperties": False
      }
    },
    "complete_disposition": {
      "type": "string",
      "description": "Prose summary of spatial relationships for Pass 2 context. Must use named anchors from ROOM ANCHOR POINTS verbatim — no compass directions. Every anchor name used must also appear in anchor_refs[]. Example: 'Jack stands at [entrance-door], body squared toward Jane who is backed against [panoramic-window-south], the [grey-textured-rug] between them.'"
    },
    "anchor_refs": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Anchor point names from ROOM ANCHOR POINTS that appear in complete_disposition. Must list at least one anchor per panel when anchor_points exist for this location. Copy names verbatim from the injected anchor data."
    },
    "environment": {
      "type": "string",
      "description": "Atmospheric or environmental state (e.g., 'lights dimming', 'rain hitting window')."
    }
  },
  "required": ["actors", "props", "complete_disposition", "environment"],
  "additionalProperties": False
}

DRAMA_REQUIREMENTS_SCHEMA = {
  "description": "Narrative-driven cinematic instructions for framing and intent.",
  "type": "object",
  "properties": {
    "shot_scale": {
      "type": "string",
      "enum": ["WS", "MS", "MCU", "CU", "ECU", "Macro"],
      "description": "Standard framing distance."
    },
    "camera_angle": {
      "type": "string",
      "enum": ["Eye-level", "Low-angle", "High-angle", "Dutch-angle", "Bird's-eye", "Worm's-eye"],
      "description": "The vertical or tilted perspective to convey power or tension."
    },
    "composition_style": {
      "type": "string",
      "enum": ["Centered", "Rule-of-thirds", "Over-the-shoulder", "Leading-lines", "Symmetry", "Frame-within-a-frame"],
      "description": "Specific visual layout law to follow for Pass 2."
    },
    "focus_priority": {
      "type": "object",
      "properties": {
        "primary_target": { "type": "string", "description": "Main actor or prop." },
        "secondary_target": { "type": ["string", "null"], "description": "Background or reaction target for rack focus." },
        "focus_depth": { "type": "string", "enum": ["Shallow", "Deep", "Rack-focus"], "description": "Bokeh/DOF intent." }
      },
      "required": ["primary_target", "focus_depth"]
    },
    "movement_intent": {
      "type": "object",
      "properties": {
        "type": {
          "type": "string",
          "enum": ["Static", "Pan", "Tilt", "Dolly-in", "Dolly-out", "Truck", "Pedestal", "Handheld-shake"]
        },
        "target_trajectory": { "type": "string", "description": "e.g., 'Follow Jane's hand' or 'Reveal the door'." },
        "dynamic_speed": { "type": "string", "enum": ["Slow", "Standard", "Burst", "None"] }
      },
      "required": ["type"]
    },
    "narrative_vibe": {
      "type": "string",
      "description": "The emotional goal of the shot (e.g., 'Claustrophobic', 'Triumphant', 'Voyeuristic')."
    }
  },
  "required": [
    "shot_scale",
    "camera_angle",
    "composition_style",
    "focus_priority",
    "movement_intent"
  ],
  "additionalProperties": False
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
                                "visual_start": {"type": "string", "description": "Still-frame at the exact moment before motion begins. SPATIAL LANGUAGE: frame positions/gaze use frame-left/frame-right (viewer's perspective); body parts use possessive anatomical ('his left hand', 'her right shoulder'). Never bare 'left'/'right' for spatial positions."},
                                "visual_end": {"type": "string", "description": "Still-frame of the NEW UNSTABLE STATE at clip end. Same spatial language as visual_start: frame-left/frame-right for positions; possessive anatomical for body parts."},
                                "motion_intent": {"type": "string", "description": "WHY the character is physically moving in this clip — their goal or intention in one sentence. motion_prompt is HOW; motion_intent is WHY. Declare the intent before writing motion_prompt: without a goal the model fills time with held poses and dead gestures. E.g. 'Pavel deflects blame to escape accountability', 'Sofya catalogs his weakness as a future weapon', 'Alisa crosses the room to reclaim the document before he reads it'."},
                                "motion_action": {"type": "string", "description": "High-level motion description, motion_action is WHAT happens here, what actors do. E.g. 'Jane walks towards the coffee table, shuts the laptop and says her like', 'Jack stands up and shakes hands with Jim, who just entered'."},
                                "motion_prompt": {"type": "string", "description": "Timestamped physical motion arc (~6s). SPATIAL LANGUAGE: lateral movement uses 'toward frame-left'/'toward frame-right' for composition descriptions; body parts use possessive anatomical ('his left hand'). Never bare 'left'/'right' for spatial positions. CHARACTER MOVEMENT uses world-space destinations — 'toward [person/door/window/furniture]', 'retreating to the entrance', 'crossing to the coffee table' — NEVER 'toward camera' or 'away from camera'. Camera tracks the character; camera behavior (dolly, zoom, pan, track) belongs in lights_and_camera."},
                                "is_reversed": {"type": "boolean", "description": "True if this panel's action is revealed in reverse playback order (e.g. fog clears to reveal a face, door opens as character enters, reflection coalesces in a window). IMPORTANT: write visual_start and visual_end in NORMAL CHRONOLOGICAL ORDER — start = before the action, end = after. The pipeline swaps them automatically before rendering. Write motion_prompt in normal chronological order too; the reversal pass generates motion_prompt_reversed. Leave motion_prompt_reversed as empty string."},
                                "motion_prompt_reversed": {"type": "string", "description": "Populated ONLY when is_reversed is true. Describes the reversed playback motion: how the scene should visually transition from visual_start (obscured) to visual_end (revealed) as perceived by the viewer. Empty string when is_reversed is false."},
                                "lights_and_camera": {"type": "string", "description": "Camera setup and lighting for this panel: shot scale (ECU/CU/MS/WIDE), camera angle, lens, lighting conditions, deviations from scene camera_master/lighting_master. When a character moves significantly in motion_prompt, state camera tracking here — e.g. 'camera tracks her as she crosses to the sofa, maintaining MS framing' or 'crash-zoom to ECU at moment of contact'. motion_prompt states where characters go; lights_and_camera states how the camera follows."},
                                "dialogue": {"type": "string", "description": f"Dialogue line, in {_LANG}, add names and male/female indicators. E.g. 'Alice (old female): What a lovely cityscape here'. David (male kid): I know."},
                                "voiceover": {"type": "string", "description": f"Off-screen narration / inner monologue text only, in {_LANG}. No voice/gender prefix — those go in voiceover_settings. Reveals subtext the viewer CANNOT see (fear, memory, desire). Never describes what is visually obvious. Must not overlap dialogue — use timestamps if needed, e.g. 'at 2.0s, after Alice finishes: Damn it!'"},
                                "voiceover_settings": {"type": "object", "description": "TTS voice parameters for this panel's voiceover. Required whenever voiceover is non-empty; use empty object {} when voiceover is empty.", "properties": {"gender": {"type": "string", "description": "Voice gender: 'male' or 'female'"}, "actor": {"type": "string", "description": "Character name whose inner voice this is, e.g. 'Pavel'"}, "age": {"type": "string", "description": "Approximate age as a string, e.g. '23', '45'"}, "tone": {"type": "string", "description": "Comma-separated emotional/delivery descriptors, e.g. 'scared, confused', 'cold, commanding', 'breathless, urgent', 'bitter, exhausted'"}}, "required": ["gender", "actor", "age", "tone"]},
                                "voiceover_timing": {
                                    "type": "string",
                                    "description": (
                                        "When to play the voiceover relative to dialogue. "
                                        "Required when both voiceover and dialogue are non-empty. "
                                        "Values: 'before_dialogue' | 'after_dialogue' | 'under_dialogue' (low VO mix) | 'during_silence'."
                                    )
                                },
                                "emotional_beat": {"type": "string", "description": "Dominant emotion of this panel (single word): tension, revelation, grief, desire, defiance, dread, relief, rage, longing, shock, shame, triumph"},
                                "hook_type": {"type": "string", "description": "Role of this panel in episode dramaturgy: cold_open | verbal_hook | escalation | emotional_capture | crystallization | confrontation | pivot | twist | tension_peak | cliffhanger | arc_bridge | arc_pickup | backlink | none. cold_open subtypes via slash: cold_open/status_reversal | cold_open/impossible_situation | cold_open/hidden_identity | cold_open/ticking_clock | cold_open/revelation. cliffhanger subtypes: cliffhanger/response_freeze | cliffhanger/revelation | cliffhanger/emotional_rupture | cliffhanger/interrupted_action. Key assignments: verbal_hook = P2 (conflict statement in ≤8 words); emotional_capture = P4 (point of no return); crystallization = P5 (strongest thumbnail candidate, stakes visceral); pivot = P⌈N×0.78⌉ (ECU reaction, no dialogue, voiceover mandatory 4–5 words); tension_peak = last panel of intermediate episodes; cliffhanger = last panel of final episode."},
                                "text_safe_composition": {"type": "boolean", "description": "True when key subjects (faces, hands, action) are composed in the middle 65% of frame height, leaving top 15% and bottom 20% clear for subtitle overlays."},
                                "panel_type": {"type": "string", "description": "Always 'narrative'. Every panel shows characters in action — no faceless atmosphere-only shots."},
                                "transition_to_next": {"type": "string", "description": "Edit cut technique to the next panel: match_cut (cut on matching shape/motion — visual_end of this panel mirrors visual_start of next), jump_cut (jarring deliberate cut for pace — allows duration 2–3s), smash_cut (sudden silence-to-action or reverse), j_cut (next panel audio begins audibly in the final 1–2s of this panel — note in sound_design), hard_cut (standard clean cut, default)."},
                                "sound_design": {"type": "string", "description": "Sonic atmosphere cue for this panel, independent of dialogue/voiceover. Required for every panel. E.g.: 'silence', 'ambient hum', 'pin-drop silence building to heartbeat at 5s', 'bass drop on cut', 'amplified footstep at 2s', 'J-cut: rain ambient from next scene starts at 5s', 'glass crack at 4s then silence'."},
                                "caption": {"type": "string"},
                                "duration": {"type": "integer"},
                                "references": {"type": "array", "items": {"type": "string"}},
                                "location_references": {"type": "array", "items": {"type": "string"}, "description": "Location/environment reference names visible in this panel. Use the specific view ref that matches the camera angle: for rooms use '{Room-Name}-View-From-Entrance' (camera at door looking in) or '{Room-Name}-View-To-Entrance' (camera at far end looking toward door); for vehicles use '{Vehicle-Name}-Exterior', '{Vehicle-Name}-Interior-From-Entrance', or '{Vehicle-Name}-Interior-To-Entrance'. Names must exactly match existing refs or rendering will skip them."},
                                "visual_disposition": {"type": "string", "description": "Spatial anchor binding generated by the disposition pass. Pins each character to a named zone/object in the room using natural-language landmark references. Injected into image prompt alongside visual_start."},
                                "state": PANEL_STATE_SCHEMA,
                                "drama_requirements": DRAMA_REQUIREMENTS_SCHEMA,
                                "camera_position": {"type": "string", "description": "Spatial anchor binding for camera position, based on state and drama_requirements"},
                            },
                            "required": ["panel_index", "motion_intent", "visual_start", "visual_end", "motion_prompt", "is_reversed", "motion_prompt_reversed", "lights_and_camera", "dialogue", "voiceover", "voiceover_settings", "emotional_beat", "hook_type", "text_safe_composition", "panel_type", "transition_to_next", "sound_design", "caption", "duration", "references", "location_references", "motion_action"]
                        }
                    },
                    "scene_trajectories": {
                        "type": "array",
                        "description": "Per-character trajectory declaration for this scene. Fill BEFORE writing any panels — this is the scene-level thinking step that anchors motion_intent, blocking, dialogue subtext, and visual_end states into a coherent arc. Declare for every named character present.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "character": {"type": "string", "description": "Character name matching their reference slug."},
                                "goal": {"type": "string", "description": "What this character wants to achieve by scene end — their objective, not their action. E.g. 'force her to sign before she calls her lawyer'."},
                                "obstacle": {"type": "string", "description": "What blocks them from the goal. External (another character, locked door) or internal (fear, conflicting desire). E.g. 'she controls the only exit and knows it'."},
                                "tactic": {"type": "string", "description": "How they try to overcome the obstacle — their approach strategy. E.g. 'manufactured urgency — fabricated deadline'."},
                                "emotional_arc": {"type": "string", "description": "Emotional trajectory across the scene. Format: 'enters [state] → [turning point] at P[N] → exits [state]'. Must commit to a specific panel. E.g. 'enters performing confidence → cracks into controlled fear at P7 → exits having recomposed the mask'."},
                                "arc": {"type": "string", "description": "What changed by scene end — win, loss, transformation, stalemate. One sentence. E.g. 'partial win: she stalls but does not leave — he retains physical control but loses information advantage'."}
                            },
                            "required": ["character", "goal", "obstacle", "tactic", "emotional_arc", "arc"]
                        }
                    },
                },
                "required": ["scene_id", "location", "panels", "scene_trajectories"]
            }
        }
    },
    "required": ["scenes"]
}

# ---------------------------------------------------------------------------
# 4-Pass schemas
# ---------------------------------------------------------------------------

_TRAJECTORY_SCHEMA = SCENE_SCHEMA["properties"]["scenes"]["items"]["properties"]["scene_trajectories"]

_VOICEOVER_SETTINGS_SCHEMA = SCENE_SCHEMA["properties"]["scenes"]["items"]["properties"]["panels"]["items"]["properties"]["voiceover_settings"]

PASS1_SCHEMA = {
    "type": "object",
    "properties": {
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scene_id": {"type": "integer"},
                    "scene_trajectories": _TRAJECTORY_SCHEMA,
                    "panels": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "panel_index": {"type": "integer"},
                                "hook_type": {"type": "string", "description": "Panel role: cold_open/status_reversal|cold_open/impossible_situation|cold_open/hidden_identity|cold_open/ticking_clock|cold_open/revelation|verbal_hook|escalation|emotional_capture|crystallization|confrontation|pivot|twist|tension_peak|cliffhanger/response_freeze|cliffhanger/revelation|cliffhanger/emotional_rupture|cliffhanger/interrupted_action"},
                                "duration": {"type": "integer", "description": "Expected seconds. cold_open ≤4, pivot 3–4, default 6."},
                                "scale": {"type": "string", "enum": ["WS", "MS", "MCU", "CU", "ECU", "Macro"], "description": "Shot scale that best serves this panel's dramatic intent."},
                                "motion_intent": {"type": "string", "description": "WHY the primary character is acting — their goal, not the action. E.g. 'Pavel deflects blame to avoid accountability'."},
                                "dialogue_seed": {"type": "string", "description": "Raw ≤8-word starter for dialogue or voiceover, expanded in Pass 3. Empty string for silent panels."},
                                "drama_requirements": DRAMA_REQUIREMENTS_SCHEMA,
                            },
                            "required": ["panel_index", "hook_type", "duration", "scale", "motion_intent", "dialogue_seed", "drama_requirements"],
                            "additionalProperties": False
                        }
                    }
                },
                "required": ["scene_id", "scene_trajectories", "panels"],
                "additionalProperties": False
            }
        }
    },
    "required": ["scenes"]
}

PASS1A_SCHEMA = {
    "type": "object",
    "properties": {
        "panels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "panel_index": {"type": "integer"},
                    "state": PANEL_STATE_SCHEMA,
                    "motion_action": {"type": "string", "description": "Scene-level summary of all actor actions in this panel. E.g. 'Jane walks to the sofa; Jack stands and crosses his arms'."},
                },
                "required": ["panel_index", "state", "motion_action"],
                "additionalProperties": False
            }
        }
    },
    "required": ["panels"]
}

PASS1B_SCHEMA = {
    "type": "object",
    "properties": {
        "panels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "panel_index": {"type": "integer"},
                    "camera_position": {"type": "string", "description": "Nearest named anchor landmark from ROOM ANCHOR POINTS."},
                    "camera_x": {"type": "number", "description": "Camera X in [0,1]: 0=image-left wall, 1=image-right wall."},
                    "camera_y": {"type": "number", "description": "Camera Y in [0,1]: 0=entrance wall, 1=far wall."},
                    "camera_z": {"type": "number", "description": "Camera height Z in [0,1]: 0.18=ground, 0.45=seated, 0.55=eye-level, 0.80=crane."},
                    "location_references": {
                        "type": "array", "items": {"type": "string"},
                        "description": "View slug(s) derived from camera position using 8-point view selection."
                    },
                    "visual_disposition": {
                        "type": "string",
                        "description": "Camera-agnostic, anchor-grounded disposition prose. Pins every actor to named room landmarks. FORBIDDEN: screen-left/right, frame-left/right, compass directions, invented anchor names."
                    },
                },
                "required": ["panel_index", "camera_position", "camera_x", "camera_y", "camera_z", "location_references", "visual_disposition"],
                "additionalProperties": False
            }
        }
    },
    "required": ["panels"]
}

PASS2_SCHEMA = {
    "type": "object",
    "properties": {
        "camera_master": {"type": "string", "description": "Dominant lens (mm), angle bias, primary lighting condition shared by ALL panels as baseline. One sentence. Example: '85mm CU bias, eye-level, harsh midday daylight from panoramic windows, deep East-wall shadows.'"},
        "lighting_master": {"type": "string", "description": "Key light direction/color/quality, fill ratio, visible practicals. All panels inherit this. Inventing a new time-of-day or light source not in visual_continuity_rules is a HARD FAILURE. One sentence."},
        "panels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "panel_index": {"type": "integer"},
                    "visual_start": {"type": "string", "description": "Freeze-frame JUST BEFORE motion begins — the action has NOT started yet. State projected through camera — 70+ words. Frame positions use frame-left/frame-right; body parts use possessive anatomical ('his left hand')."},
                    "visual_end": {"type": "string", "description": "New unstable state after action — 70+ words. Same spatial language as visual_start."},
                    "lights_and_camera": {"type": "string", "description": "Shot scale, angle, lens, lighting. State camera tracking when character moves significantly."},
                    "references": {"type": "array", "items": {"type": "string"}, "description": "Character/prop reference slugs physically visible in this panel only."},
                    "location_references": {"type": "array", "items": {"type": "string"}, "description": "Location view ref slug(s) matching camera angle. Rooms have 8 views — select by camera_x/camera_y: y≤0.20→View-From-Entrance, y≥0.80→View-To-Entrance, x≤0.20→View-From-Left-Wall, x≥0.80→View-From-Right-Wall, center→View-Center-To-Far or View-Center-To-Entrance; special: View-By-Far-Wall (1m from far wall, silhouette shots), View-By-Entrance (1m from entrance, door fills frame). Use only slugs that appear in ROOM ANCHOR POINTS."},
                    "camera_position": {"type": "string", "description": "Where camera is placed relative to room anchors (textual landmark name)."},
                    "camera_x": {"type": "number", "description": "Camera X in room anchor space [0,1]: 0=image-left wall, 1=image-right wall."},
                    "camera_y": {"type": "number", "description": "Camera Y in room anchor space [0,1]: 0=entrance wall, 1=far wall."},
                    "camera_z": {"type": "number", "description": "Camera height Z [0,1]: 0=floor, 1=ceiling. Typical: 0.18=ground, 0.30=waist, 0.55=eye-level standing, 0.80=overhead crane."},
                    "text_safe_composition": {"type": "boolean", "description": "True when key subjects are in middle 65% of frame height."},
                    "panel_type": {"type": "string", "description": "Always 'narrative'."},
                },
                "required": ["panel_index", "visual_start", "visual_end", "lights_and_camera", "references", "location_references", "text_safe_composition", "panel_type", "camera_x", "camera_y", "camera_z"],
            }
        }
    },
    "required": ["panels", "camera_master", "lighting_master"]
}

PASS3_SCHEMA = {
    "type": "object",
    "properties": {
        "nitpicker_report": {"type": "string"},
        "shit_redo_report": {"type": "string"},
        "panels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "panel_index": {"type": "integer"},
                    "motion_prompt": {"type": "string", "description": "Timestamped physical motion arc, 100+ words. World-space destinations only — never 'toward camera'."},
                    "is_reversed": {"type": "boolean"},
                    "motion_prompt_reversed": {"type": "string", "description": "Populated only when is_reversed=true. Empty string otherwise."},
                    "dialogue": {"type": "string", "description": f"Spoken line in {_LANG}. ≤8 words. Include speaker name/gender prefix."},
                    "voiceover": {"type": "string", "description": f"Inner monologue in {_LANG}. 4–5 words for pivot panels. No voice prefix."},
                    "voiceover_settings": _VOICEOVER_SETTINGS_SCHEMA,
                    "voiceover_timing": {"type": "string", "description": "before_dialogue | after_dialogue | under_dialogue | during_silence. Required when both voiceover and dialogue are non-empty."},
                    "emotional_beat": {"type": "string", "description": "Dominant visible emotion at visual_end: triumph|rage|shame|defiance|dread|shock|confrontation|revelation|tension|grief|desire"},
                    "hook_type": {"type": "string", "description": "May refine Pass 1 hook_type based on final motion/audio shape."},
                    "transition_to_next": {"type": "string", "description": "match_cut | jump_cut | smash_cut | j_cut | hard_cut"},
                    "sound_design": {"type": "string"},
                    "caption": {"type": "string", "description": "≤40 chars. Hook, not summary — subtext or open question."},
                    "duration": {"type": "integer"},
                },
                "required": ["panel_index", "motion_prompt", "is_reversed", "motion_prompt_reversed", "dialogue", "voiceover", "voiceover_settings", "emotional_beat", "hook_type", "transition_to_next", "sound_design", "caption", "duration"],
            }
        }
    },
    "required": ["panels", "nitpicker_report"]
}

CHARACTER_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the reference. Avoid punctuation, quotes and parenthesis, use only letters, digits and hyphens."},
            "logline_subject_info": {"type": "string", "description": "One-sentence semantic description of who/what this is in the story (role, relationship, function). Used to deduplicate refs across runs — must be unique enough to distinguish from similarly-named entities."},
            "visual_desc": {"type": "string", "description": "verbose detailed description for the reference image generation"},
            "type": {"type": "string", "description": "Character, location, object, interface, room, vehicle, outdoor"},
            "video_visual_desc": {"type": "string", "description": "Concise visual description for scene context injection. Must preserve: physical build, clothing, face, and — for characters — ALL carry items (bag type and placement, holster location, wallet pocket, keys, badge). Omitting carry items causes actors to pull weapons/phones from thin air in generated scenes."},
            "behavioral_signature": {"type": "string", "description": "How this character behaves under pressure: their default power move, deflection strategy, and involuntary tell. Used by the scene generator for motion_intent and dialogue subtext. Leave empty for location/room/vehicle/object refs. E.g. 'Under pressure: retreats to bureaucratic procedure — cites rules, demands paperwork, buys time through process. Power move: silence and stillness while the other person fills the void. Tell: touches left cuff link when lying.'"},
            "physical_vocabulary": {"type": "string", "description": "How this character habitually occupies space and moves — their physical signature used by the scene generator for blocking. Leave empty for location/room/vehicle/object refs. E.g. 'Never sits during confrontation — paces or leans against a surface. Invades space deliberately when he wants something, closing distance by 20cm. Hands always visible and deliberately still. Retreating is not in his vocabulary — turns his back instead of stepping away.'"},
            "style_reference": {"type": "string", "description": "Name of the existing or new reference, for details consistency. E.g. for view to entrance, use view from entrance."},
            "variations": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Variation ref names for this character — different outfits or context-specific appearances. "
                    "E.g. ['Alisa-Jeans', 'Alisa-Gown', 'Alisa-Bathrobe']. "
                    "Populate for the PRIMARY character ref only. Leave empty for variation refs, locations, and objects."
                )
            },
            "character_ref": {
                "type": "string",
                "description": (
                    "Parent character ref name this entry is a variation of. "
                    "E.g. 'Alisa' for 'Alisa-Gown'. Empty for primary refs, locations, and objects."
                )
            },
            "context": {
                "type": "string",
                "description": (
                    "When this variation applies — scene context trigger. "
                    "E.g. 'Evening formal event, theater, dress code required'. "
                    "Used by Pass 1A to select visual_ref per panel. Empty for primary refs."
                )
            },
        },
        "required": ["name", "logline_subject_info", "visual_desc", "type", "style_reference", "video_visual_desc"]
    }
}

ROOM_VOCABULARY_SCHEMA = {
    "type": "object",
    "properties": {
        "named_positions": {
            "type": "array",
            "description": (
                "Every named character position and shared landmark in the room. "
                "Each entry becomes a stable anchor label used verbatim across all views."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "kebab-case anchor label, e.g. 'amanda-desk'"},
                    "description": {
                        "type": "string",
                        "description": (
                            "Full placement spec: furniture type, exact location in room, orientation, "
                            "and items on/near it. View-neutral — no image-left/right references."
                        ),
                    },
                },
                "required": ["id", "description"],
            },
        },
    },
    "required": ["named_positions"],
}

ROOM_DETAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "enriched_visual_desc": {
            "type": "string",
            "description": (
                "Rewritten visual_desc for this single camera view. Incorporates all named positions "
                "and equipment from the shared vocabulary. Preserves the camera angle of this view."
            ),
        },
    },
    "required": ["enriched_visual_desc"],
}

ENRICHMENT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Exact name matching an existing reference (letters, digits, hyphens only)."},
            "visual_desc_additions": {"type": "string", "description": "Specific visual details found in the text that are NOT yet in the existing description. Props, materials, colors, spatial arrangement, textures, inscriptions, etc. Empty string if nothing new found."},
            "behavioral_signature_additions": {"type": "string", "description": "New behavioral evidence found in the scenes — power moves, deflection strategies, tells — that refines or extends the existing behavioral_signature. Characters only; empty string for locations/rooms/vehicles/objects. Empty string if nothing new found."},
            "physical_vocabulary_additions": {"type": "string", "description": "New evidence of how the character habitually occupies space — posture, movement patterns, signature gestures — not yet captured in physical_vocabulary. Characters only; empty string for locations/rooms/vehicles/objects. Empty string if nothing new found."},
        },
        "required": ["name", "visual_desc_additions", "behavioral_signature_additions", "physical_vocabulary_additions"]
    }
}

REVERSAL_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "panel_index": {"type": "integer"},
            "motion_prompt_reversed": {"type": "string"},
            "visual_start_explicit": {
                "type": "string",
                "description": (
                    "Fully explicit rewrite of the original visual_end (which becomes visual_start after swap). "
                    "Must include shot type (ECU/CU/MS/MLS/LS), camera angle, character positions in frame, "
                    "key props, lighting. No 'same framing', 'as before', or implicit references allowed."
                )
            }
        },
        "required": ["panel_index", "motion_prompt_reversed", "visual_start_explicit"]
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
        "shot_impossible": {
            "type": "boolean",
            "description": (
                "True if the panel description contains a physically impossible shot combination "
                "that no amount of image refinement can fix — e.g. ECU face + distant body part "
                "visible in the same frame, two incompatible shot scales in one visual_start/visual_end. "
                "When true: set needs_refinement=false, leave refinement_prompt empty, "
                "describe the conflict in shot_impossible_reason. "
                "This panel requires a SCREENPLAY REWRITE, not image regeneration."
            ),
        },
        "shot_impossible_reason": {
            "type": "string",
            "description": (
                "If shot_impossible is true: describe the specific scale conflict — "
                "which two elements are mutually exclusive in one frame and why. "
                "Empty string otherwise."
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
        "shot_impossible",
        "shot_impossible_reason",
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
        "video_visual_desc": {"type": "string", "description": "Concise updated description for scene context injection. Must preserve all carry items (bag, holster, pockets, badge) — these are referenced when characters retrieve objects in panels."},
        "behavioral_signature": {"type": "string", "description": "Updated behavioral DNA: power move, deflection strategy, involuntary tell. Merge existing with new evidence. Characters only — empty string for locations/rooms/vehicles/objects."},
        "physical_vocabulary": {"type": "string", "description": "Updated movement and space-occupation signature: posture, movement patterns, signature gestures. Merge existing with new evidence. Characters only — empty string for locations/rooms/vehicles/objects."},
    },
    "required": ["visual_desc", "video_visual_desc", "behavioral_signature", "physical_vocabulary"]
}

SPATIAL_DISPOSITION_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "panel_index": {"type": "integer"},
            "visual_disposition": {
                "type": "string",
                "description": (
                    "Spatial anchor binding for this panel. "
                    "Pins each character to a named zone/object using natural-language landmark references. "
                    "Self-contained — no 'same as before' or cross-panel references."
                ),
            },
            "swap_view": {
                "type": "boolean",
                "description": (
                    "True if the current view_type is cinematically wrong for this panel. "
                    "Set to true for: (A) face/close-up shots where the inferred camera side "
                    "contradicts view_type or puts the subject's back to camera; "
                    "(C) action/wide-single shots with a clear spatial signal (e.g. desk or "
                    "furniture in foreground indicates camera on the far/desk side). "
                    "Never set for two-character wide/medium shots (B), profiles, silhouettes, "
                    "rear shots, inserts (D), or overhead shots. False when unsure."
                ),
            },
            "swap_view_reason": {
                "type": "string",
                "description": (
                    "Required for every panel. One sentence: shot category (A/B/C/D), "
                    "the primary spatial signal used to infer camera side, and the swap decision reached. "
                    "E.g. 'Category A face shot, entrance behind subject → camera on far side → "
                    "To-Entrance; current From-Entrance wrong → swap=true'."
                ),
            },
        },
        "required": ["panel_index", "visual_disposition", "swap_view", "swap_view_reason"],
    },
}

SPATIAL_REWRITE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "panel_index": {"type": "integer"},
            "visual_start_rewrite": {
                "type": "string",
                "description": (
                    "Rewritten visual_start that corrects a factual spatial contradiction "
                    "detected by comparing the original with the anchor-grounded visual_disposition. "
                    "Correct ONLY contradicted spatial terms (wrong frame-left/right, wrong depth label, "
                    "impossible subject position). Preserve tone, shot scale, lighting, and all "
                    "non-spatial prose. Empty string when visual_start is already consistent."
                ),
            },
            "motion_prompt_rewrite": {
                "type": "string",
                "description": (
                    "Rewritten motion_prompt that corrects directional/positional errors "
                    "contradicted by the anchor-grounded visual_disposition. "
                    "Correct ONLY the contradicted direction or depth term "
                    "(e.g. 'frame-right' → 'frame-left'). Preserve all motion dynamics, "
                    "timing, camera movement, and non-spatial language. "
                    "Empty string when motion_prompt is absent or already consistent."
                ),
            },
        },
        "required": ["panel_index", "visual_start_rewrite", "motion_prompt_rewrite"],
    },
}

ANCHOR_SCHEMA = {
    "type": "object",
    "properties": {
        "axes": {
            "type": "string",
            "description": (
                "Coordinate system definition. All positions are normalized [0,1] fractions. "
                "X = fraction of room width: 0 = image-left wall as seen in View-From-Entrance, "
                "1 = image-right wall. Y = fraction of room depth: 0 = entrance wall, 1 = far wall. "
                "Z = fraction of room height: 0 = floor, 1 = ceiling. "
                "8-point view projections: "
                "View-From-Entrance (y≈0): lateral=X, depth=Y. "
                "View-To-Entrance (y≈1): x_mirrored=1-x, depth reversed. "
                "View-From-Left-Wall (x≈0, looking toward x=1 wall): lateral=Y, depth=X. "
                "View-From-Right-Wall (x≈1, looking toward x=0 wall): lateral=1-Y, depth=1-X. "
                "View-Center-To-Far (center, looking toward y=1): same as From-Entrance. "
                "View-Center-To-Entrance (center, looking toward y=0): same as To-Entrance. "
                "View-By-Far-Wall (y≈0.85, looking toward y=1): same as From-Entrance; far wall fills frame. "
                "View-By-Entrance (y≈0.15, looking toward y=0): same as To-Entrance; entrance door fills frame."
            ),
        },
        "room_m": {
            "type": "array",
            "items": {"type": "number"},
            "description": "[width_m, depth_m] in meters — used for physical distance calculations only, not for coordinates",
        },
        "objects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "kebab-case identifier, e.g. 'marble-table-south'"},
                    "label": {"type": "string"},
                    "x": {"type": "number", "description": "normalized [0,1] center: 0 = image-left wall, 1 = image-right wall"},
                    "y": {"type": "number", "description": "normalized [0,1] center: 0 = entrance wall, 1 = far wall"},
                    "z": {"type": "number", "description": "normalized [0,1] center: 0 = floor, 1 = ceiling"},
                    "width_x": {"type": "number", "description": "Footprint width along X axis as fraction of room width. E.g. table spanning x=0.3–0.7 → width_x=0.4. Use 0 for point features (lamps, photos, door handles)."},
                    "depth_y": {"type": "number", "description": "Footprint depth along Y axis as fraction of room depth. Use 0 for point features."},
                    "facing_degrees_y": {"type": "number", "description": "Horizontal facing yaw 0–360°. 0=toward entrance (y=0), 90=toward image-right (x=1), 180=toward far wall (y=1), 270=toward image-left (x=0). For objects with a natural front face (chairs, sofas, screens, desks). Use -1 for omnidirectional objects (lamps, pillars, rugs)."},
                    "notes": {"type": "string", "description": "Position description using image-left/image-right/entrance-side/far-side terms. No compass directions."},
                },
                "required": ["id", "label", "x", "y", "z", "width_x", "depth_y", "facing_degrees_y"],
            },
        },
        "zones": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "kebab-case zone id, e.g. 'bar-area'"},
                    "label": {"type": "string"},
                    "x": {"type": "number", "description": "normalized [0,1] zone center: 0 = image-left wall, 1 = image-right wall"},
                    "y": {"type": "number", "description": "normalized [0,1] zone center: 0 = entrance wall, 1 = far wall"},
                    "visual_disposition_hint": {
                        "type": "string",
                        "description": (
                            "Natural-language anchor phrase for View-From-Entrance (camera at entrance looking in). "
                            "Use ONLY physical landmark names and image-left/image-right wall terms derived from X: "
                            "x < 0.35 = image-left side; x > 0.65 = image-right side; else center. "
                            "NO screen-direction words (frame-left, frame-right, screen-left). "
                            "Include a DEPTH chain using named anchors. "
                            "Example: 'host at far side of desk (image-right, x≈0.7); desk surface between camera and host; "
                            "host visible from mid-chest up above desk edge; city-window wall behind. "
                            "DEPTH: entrance doorway → desk → host mid-ground → city-window wall'."
                        ),
                    },
                    "visual_disposition_hint_to_entrance": {
                        "type": "string",
                        "description": (
                            "Natural-language anchor phrase for View-To-Entrance / View-Opposite / View-Center-To-Entrance "
                            "(camera at far wall looking toward entrance). "
                            "TWO rules apply simultaneously: "
                            "(1) Depth stack is REVERSED — far-wall objects are now nearest to camera, entrance is background. "
                            "(2) IMAGE-LEFT/RIGHT are SWAPPED — x_mirrored = 1 - x. "
                            "Use ONLY physical landmark names and mirrored image-left/image-right terms. "
                            "NO screen-direction words (frame-left, frame-right). "
                            "Example: sofa at x=0.05 → x_mirrored=0.95 → image-right in this view. "
                            "Write: 'sofa in mid-ground image-right (x_mirrored≈0.95); far window-wall nearest camera; "
                            "entrance doorway in far background. "
                            "DEPTH: window-wall → sofa mid-ground → entrance doorway'."
                        ),
                    },
                    "visual_disposition_hint_lateral": {
                        "type": "string",
                        "description": (
                            "Natural-language anchor phrase for View-From-Left-Wall / View-From-Right-Wall "
                            "(camera on a side wall, looking across the room). "
                            "Axis re-mapping: depth runs along X (not Y); "
                            "the Y axis determines which objects appear entrance-side vs far-side in frame. "
                            "For View-From-Left-Wall (camera x≈0, looking toward image-right wall x=1): "
                            "  depth = x (higher x = farther); entrance-side objects (low Y) appear to one side, "
                            "  far-wall objects (high Y) to the other. "
                            "Use ONLY physical landmark names. NO screen-direction words. "
                            "State which wall is the far background and the entrance-side edge. "
                            "Include DEPTH chain along X axis. "
                            "Example: 'sofa (x≈0.55, y≈0.6) mid-depth in room, entrance-side edge visible; "
                            "image-right wall is far background; image-left wall is behind camera. "
                            "DEPTH: image-left-wall edge → sofa → image-right wall background'."
                        ),
                    },
                },
                "required": ["id", "label", "x", "y", "visual_disposition_hint"],
            },
        },
    },
    "required": ["axes", "room_m", "objects", "zones"],
}

ROOM_VIEW_QA_SCHEMA = {
    "type": "object",
    "properties": {
        "consistency_score": {
            "type": "integer",
            "description": (
                "0–10: how well floor material, wall surfaces, furniture pieces, and lighting "
                "in the derived view match the source view. "
                "10 = identical materials throughout. 0 = completely different room."
            ),
        },
        "geometry_score": {
            "type": "integer",
            "description": (
                "0–10: how correctly the perspective and spatial re-mapping match the declared "
                "camera position. 10 = correct far wall, correct depth, correct lateral mapping. "
                "0 = wrong wall shown, impossible perspective, or entrance visible when it should be hidden."
            ),
        },
        "needs_regeneration": {
            "type": "boolean",
            "description": "True when consistency_score < threshold OR geometry_score < threshold.",
        },
        "issues": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Specific discrepancies found: one item per issue. "
                "Examples: 'floor appears light wood instead of dark concrete', "
                "'entrance door visible in background but camera should face away from it', "
                "'bookcase missing from far wall'."
            ),
        },
        "regeneration_prompt": {
            "type": "string",
            "description": (
                "Concrete fix instructions to append to visual_desc for re-generation. "
                "Name exact elements to correct. Empty string when needs_regeneration=false."
            ),
        },
    },
    "required": ["consistency_score", "geometry_score", "needs_regeneration", "issues", "regeneration_prompt"],
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

