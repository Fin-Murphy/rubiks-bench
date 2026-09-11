# Project Brief — Rubik's Cube LLM Solver

**Orchestrator:** session `orchestrator` (makes all high-level decisions; message it with questions/results)
**Team:** `researcher` (web/doc research), `designer` (product/UX/protocol specs), `programmer` (implementation)
**Project root:** `/Users/fin/Desktop/orchbrain/rubiks-llm/`

## Goal
Represent a 3x3 Rubik's cube programmatically as text for an LLM, and let an LLM try to solve it
via a turn-based tool that only accepts real cube moves.

## Core loop (user requirement)
1. Script starts with a clean text representation of a SOLVED cube.
2. Command `scramble` sets the cube to a random, legal configuration.
3. Script accepts moves in standard notation (e.g. `U2`), applies them, returns the new text state.
4. LLM reads the state, makes another move. Repeat until solved or budget exhausted.

## Notation (source: jperm.net/3x3/moves — "Rubik's Cube Move Notation.pdf" in /Users/fin/Desktop/orchbrain/)
- Face turns: U D R L F B — clockwise as if facing that side. `'` = counterclockwise, `2` = 180° (`2'` also accepted).
- Wide moves (2 layers): `Uw Dw Rw Lw Fw Bw` or lowercase `u d r l f b` (+ `'`, `2`). Uppercase `I` is not a move.
- Rotations: `x y z` (x follows R, y follows U, z follows F) (+ `'`, `2`).
- Slices: `M E S` (M follows L, E follows D, S follows F) (+ `'`, `2`).

## Decided conventions (orchestrator decisions)
- **Language:** Python 3, engine is stdlib-only. Tests with pytest.
- **Build vs acquire:** write our own small engine; cross-validate against an established reference library in tests.
- **Internal model:** 54-facelet array in Kociemba order U1-9, R1-9, F1-9, D1-9, L1-9, B1-9
  (each face read row-by-row; U viewed with B at top, D viewed with F at top, L/F/R/B viewed with U at top).
- **Color scheme (WCA):** U=White, F=Green, R=Red, D=Yellow, L=Orange, B=Blue.
- **Solved check:** each face uniform (orientation-independent, so rotations/slices don't break it).
- **Scramble:** `scramble` = uniform random-state (all 43,252,003,274,489,856,000 legal states, via cubie
  permutation/orientation with parity + twist + flip constraints). `scramble N` = random N-move scramble
  (no consecutive same-face moves) for difficulty levels. Scramble is always legal by construction.
- **Turn-based:** the LLM-facing tool accepts only valid cube moves; invalid input is rejected with an
  error and does not change state.

## Agent hookup (orchestrator decision)
- No Anthropic API key on this machine; Claude Code CLI (2.1.269) is installed and authenticated.
- **Python MCP server** (stdio, official `mcp` SDK) owns the game: holds the cube, enforces move budget,
  keeps the scramble hidden, logs every turn to JSONL, decides solved/lost. Scramble/reset are NOT LLM tools.
- **Runner script** launches `claude -p` with `--strict-mcp-config` (only our server) and built-in tools
  disabled, from an empty temp cwd, so the model can only make cube moves and can't read source/logs.
- Same server is usable interactively from Claude Code / Claude Desktop.
- Env: Python 3.14.7 (Homebrew, externally managed) → project venv at `rubiks-llm/.venv`.

## Deliverables / docs
- `docs/RESEARCH.md` — researcher
- `docs/DESIGN.md` — designer
- `cube.py`, `cli.py`, `tests/`, agent harness — programmer
