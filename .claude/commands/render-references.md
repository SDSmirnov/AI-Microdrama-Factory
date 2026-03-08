Arguments: $ARGUMENTS

Render missing character reference portraits via `python cli.py refs`.

## Argument mapping

Parse `$ARGUMENTS` and translate to the appropriate flags:

| User input | Command |
|---|---|
| _(empty)_ | `python cli.py refs` |
| `--custom-prompts` | `python cli.py refs --custom-prompts` |
| `--llm gemini` | `python cli.py --llm gemini refs` |
| `--llm debug` | `python cli.py --llm debug refs` |
| `--llm debug --custom-prompts` | `python cli.py --llm debug refs --custom-prompts` |

`--llm` is a global flag placed **before** the subcommand. Supported values: `openrouter` (default), `gemini`, `grok`, `debug`.
`--llm debug` logs all prompts/responses to disk without calling any API — useful for offline testing.

Examples:
- `/render-references` → `python cli.py refs`
- `/render-references --custom-prompts` → `python cli.py refs --custom-prompts`
- `/render-references --llm debug` → `python cli.py --llm debug refs`

## Prerequisites

- API key for the chosen `--llm` backend must be set (`OPENROUTER_API_KEY` for default, `IMG_AI_API_KEY` for gemini, `XAI_API_KEY` for grok). Not required for `--llm debug`.
- `ref_thriller/*.json` files must exist (created by `/cast-characters`).

## Execution

Build the command from the argument mapping above and run it with Bash. Stream output to the user.

After completion, report:
- Which character reference PNGs were generated (or skipped as already existing)
- Any errors encountered
- Where output files were written (`ref_thriller/`)
