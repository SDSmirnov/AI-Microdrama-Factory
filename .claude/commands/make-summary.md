Novel file: $ARGUMENTS

Generate a chapter summary for the next chapter via `python cli.py summary`.

## Argument mapping

Parse `$ARGUMENTS` as the novel file path (first token); optional second token is the output path.

| User input | Command |
|---|---|
| `s01e01.txt` | `python cli.py summary s01e01.txt` |
| `s01e01.txt chapter_summary.txt` | `python cli.py summary s01e01.txt --output chapter_summary.txt` |
| `s01e01.txt --llm gemini` | `python cli.py --llm gemini summary s01e01.txt` |

Default output path: `chapter_summary.txt`.

## What the command does

Reads the novel file, `cinematic_render/animation_metadata.json` (if present), and `ref_thriller/*.json` character references, then asks the LLM to produce a **Chapter Summary** covering:

1. **Plot state** — key events, unresolved conflicts
2. **Character states** — who is where, what changed, emotional arc
3. **Visual continuity** — looks, locations, lighting/color palette, camera style
4. **Narrative thread** — cliffhanger or setup that carries into the next chapter
5. **Production notes** — visual motifs, recurring symbols, tone
6. **Cliffhanger chain** — classifies the episode-ending cliffhanger by type (physical_threat / revelation / emotional_rupture / interrupted_action) and recommends what type to use next to avoid audience fatigue

## Execution

Build the command from the argument mapping above and run it with Bash. Stream output to the user.

After completion, report:
- Path where summary was written (`chapter_summary.txt` by default)
- Any errors encountered
