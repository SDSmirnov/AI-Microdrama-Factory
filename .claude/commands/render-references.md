Arguments: $ARGUMENTS

Render missing character reference portraits via `python cli.py refs`.

## Argument mapping

Parse `$ARGUMENTS` and translate to the appropriate flags:

| User input | Command |
|---|---|
| _(empty)_ | `python cli.py refs` |
| `--custom-prompts` | `python cli.py refs --custom-prompts` |

Examples:
- `/render-references` → `python cli.py refs`
- `/render-references --custom-prompts` → `python cli.py refs --custom-prompts`

## Prerequisites

- `OPENROUTER_API_KEY` must be set in the environment.
- `ref_thriller/*.json` files must exist (created by `/cast-characters`).

## Execution

Build the command from the argument mapping above and run it with Bash. Stream output to the user.

After completion, report:
- Which character reference PNGs were generated (or skipped as already existing)
- Any errors encountered
- Where output files were written (`ref_thriller/`)
