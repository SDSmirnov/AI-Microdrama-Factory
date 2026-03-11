Read the novel file at path: $ARGUMENTS

Analyze the full text and extract key metadata for cinematic adaptation. Output a JSON object:

```json
{
  "genre": ["genre1", "genre2"],
  "setting": {"period": "...", "location": "...", "world_type": "realistic|fantasy|sci-fi|alternate_history"},
  "pov": "First-person|Third-person limited|Third-person omniscient|Second-person",
  "tone": ["tone1", "tone2"],
  "main_character": {"name": "...", "description": "brief visual description"},
  "special_elements": ["magic systems, technology, game mechanics, etc."],
  "visual_atmosphere": ["dark alleys", "grand ballrooms", "medieval castles", etc.]
}
```

Analysis guidelines:
1. **Genre** — primary genres: Fantasy, Sci-Fi, Historical, LitRPG, Romance, Thriller, Noir, etc.
2. **Setting** — time period, location, world type
3. **POV** — narrative perspective
4. **Tone** — atmospheric qualities: dark, heroic, comedic, romantic, gritty, tense, etc.
5. **Main Character** — name + brief visual description of protagonist
6. **Special Elements** — magic systems, technology, supernatural elements, game mechanics, etc.
7. **Visual Atmosphere** — dominant visual environments across the story

After outputting the JSON, recommend the best visual style preset for this novel:

| Preset | Best for |
|--------|----------|
| `vertical_9_16_microdrama` | Default portrait format for TikTok/Reels/Shorts (9:16). One episode per narrative chapter; multi-POV (pov_a / pov_b / confrontation) supported. Best for fast-paced stories. |
| `vertical_9_16_long_arc` | Same portrait format, but episodes grouped into arc units of 2–3 episodes each (arc_open → arc_mid → arc_close). Better for slow-burn narratives, romance, and character-driven drama. |

Explain your recommendation in 2–3 sentences referencing the novel's specific qualities.
