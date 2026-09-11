# DESIGN.md — Rubik's Cube LLM Solver

Status: supersedes the "Claude API tool use" framing in the original brief. Per orchestrator
decision (2026-09-11): the agent plays through an **MCP server**, driven by headless
`claude -p` (Claude Code CLI), because no Anthropic API key is configured on this machine but
the CLI is installed and authenticated. §2 and §4 are written for that architecture. Everything
else (state format, game rules, human CLI, evaluation) is architecture-agnostic.

Conventions this doc assumes (from `PROJECT_BRIEF.md`, not reopened here): Python 3 stdlib
engine, 54-facelet array in Kociemba order `U1-9 R1-9 F1-9 D1-9 L1-9 B1-9` (each face read
row-by-row; U viewed with B at top, D viewed with F at top, L/F/R/B viewed with U at top), WCA
colors (U=White, F=Green, R=Red, D=Yellow, L=Orange, B=Blue), solved = every face uniform
(orientation-independent), scramble is server-side and always legal by construction.

---

## 1. Text state format

### Design choice

**Unfolded cross net, labelled per-face grids, single-letter WCA color codes, no piece-based
alternative.** Reasoning:

- Spatial adjacency (which sticker touches which neighboring face) is exactly what the net
  preserves and a flat 54-character string throws away. This is the single biggest lever for
  letting an LLM reason about the cube instead of just pattern-matching.
- **Color letters, not face-position letters, fill the grid cells.** The grid cell is the actual
  varying game state (a sticker's color); the face position is fixed and only needs to be said
  once, as a block header. Printing `U U U` for a solved U face conflates "this is the U face"
  with "this sticker is colored X" — ambiguous the moment the cube is scrambled. Colors alone are
  unambiguous.
- **Face headers are spelled out** (`U (Up)`, not bare `U`) so they can never be misread as grid
  content. This matters because two color codes (`R`=Red, `B`=Blue) unavoidably collide with two
  position letters (`R`=Right, `B`=Back) — the same overlap every cubing community lives with.
  Keeping position letters *only* in headers/prose and color letters *only* inside grids removes
  the ambiguity structurally instead of inventing non-standard color codes.
- A **footer with a computed uniform-sticker count** is included on every response. LLMs are
  unreliable at visually counting a 3×3×6 grid; computing it server-side and handing over the
  number is cheap and removes an entire class of self-assessment error.

**Reviewed against `RESEARCH.md` §5 (prior work on LLMs + Rubik's Cube) — kept the net, did not
switch to the flat 54-character string.** RESEARCH.md's closing synthesis suggests a flat string,
but flags that explicitly as the researcher's own inference, not a finding from any cited study —
nothing found there actually compares net-style vs. flat-string representations for LLM cube
solving. The one concrete, *sourced* mechanism that does bear on this choice — "state-tracking
failures" under complexity (the complexity-limits paper, RESEARCH.md §5) — argues for the net, not
against it: a flat string forces the model to reconstruct sticker adjacency from a memorized,
invisible index scheme, while the net makes that same adjacency visually explicit, which is the
more direct way to reduce state-tracking burden. The net also already satisfies the paper's actual
stated preference ("a fixed-order, fixed-width string beats anything requiring the model to infer
structure") — its layout is just as deterministic and fixed turn-to-turn as a flat string, spelled
out exactly in §4; it isn't the free-form/variable structure that finding warns against. Also
decided **against** adding a `Compact (URFDLB): ...` line to the footer (raised as an option): the
~20 tokens/turn would buy a second, parallel encoding of the same state with no cited benefit to
the model's reasoning — the compact form's actual use is machine logging (§6), where it already
appears without ever being shown to the LLM.

### Layout algorithm

1. Render each face as 3 rows of 3 color letters, space-separated, in Kociemba row-major order
   for that face (`face1 face2 face3` / `face4 face5 face6` / `face7 face8 face9`).
2. Fixed-column layout (0-indexed, left-aligned, no trailing whitespace on any line). Middle-band
   face `k` (L=0, F=1, R=2, B=3, this is the standard net unfolding order — left to right — and is
   independent of the U R F D L B storage order) starts at column `2 + 12*k`: L=2, F=14, R=26,
   B=38. Print, in order: the `U (Up)` header and U's 3 grid rows, all starting at column 14 (so U
   sits directly above F); a blank line; one header line with `L (Left)` at column 2, `F (Front)`
   at column 14, `R (Right)` at column 26, `B (Back)` at column 38; the L/F/R/B grid rows printed
   side by side at those same 4 columns; a blank line; the `D (Down)` header and D's 3 grid rows,
   all starting at column 14 (directly below F).
3. Append a footer:
   ```
   Moves used: {moves_used}/{move_budget}
   Uniform stickers: {uniform_count}/54
   Status: {STATUS_WORD} — {status message}
   ```
   `uniform_count` = sum over the 6 faces of (stickers matching that face's most common color).
   This is deliberately the same orientation-independent metric as the solved check — a cube that
   is solved-but-rotated (e.g. after `y`) scores 54/54, not some lower number from comparing
   against a fixed reference coloring. `STATUS_WORD` ∈ `IN_PROGRESS`, `SOLVED`, `OUT_OF_MOVES`
   (see §2/§3). The footer is identical in shape whether it follows `get_state` or `make_move`.

Color codes (uppercase, one letter): `W`=White `Y`=Yellow `G`=Green `R`=Red `O`=Orange `B`=Blue.

Implementation note: expose the pure renderer (net + color grid, no footer) as one function in
`cube.py` (e.g. `render_state(state) -> str`) and reuse it from the MCP server, `cli.py`, and any
test/debug tooling, so the human CLI and the LLM-facing tool can never drift out of sync. Also
expose a compact 54-character form (`U` cells then `R` then `F` then `D` then `L` then `B`, each
cell one uppercase color letter, no separators) for logging — see §6.

### Exact example: solved state

```
              U (Up)
              W W W
              W W W
              W W W

  L (Left)    F (Front)   R (Right)   B (Back)
  O O O       G G G       R R R       B B B
  O O O       G G G       R R R       B B B
  O O O       G G G       R R R       B B B

              D (Down)
              Y Y Y
              Y Y Y
              Y Y Y
```
Compact form: `WWWWWWWWWRRRRRRRRRGGGGGGGGGYYYYYYYYYOOOOOOOOOBBBBBBBBB`

### Exact example: state after `R` (applied to the solved cube)

```
              U (Up)
              W W G
              W W G
              W W G

  L (Left)    F (Front)   R (Right)   B (Back)
  O O O       G G Y       R R R       W B B
  O O O       G G Y       R R R       W B B
  O O O       G G Y       R R R       W B B

              D (Down)
              Y Y B
              Y Y B
              Y Y B
```
Compact form: `WWGWWGWWGRRRRRRRRRGGYGGYGGYYYBYYBYYBOOOOOOOOOWBBWBBWBB`

Uniform stickers: 42/54 (R and L faces untouched at 9/9 each; U, F, D, B each drop to 6/9). Both
examples above were generated and cross-checked programmatically (permutation-cycle derivation,
not hand-traced) before being written into this doc — use them as a golden test case for the
engine and the renderer.

---

## 2. MCP tool protocol

### Tools

Exactly two tools, both served by one stdio MCP server (suggested filename `mcp_server.py`).
**No `scramble` or `reset` tool exists.** Those are game setup, not gameplay, and giving the LLM a
`scramble` tool would let it inspect or replay its own scramble. The runner configures scramble
seed/depth and the move budget via server startup config (env vars, below); the server scrambles
once at startup and never re-scrambles for the lifetime of the process.

**`get_state`** — read-only, free (never touches the move budget), safe to call any number of
times including after the game has ended.
```json
{
  "name": "get_state",
  "description": "Return the current cube state as text, without making any move. Free — does not use any of the move budget.",
  "inputSchema": {
    "type": "object",
    "properties": {},
    "additionalProperties": false
  }
}
```

**`make_move`** — applies exactly one move.
```json
{
  "name": "make_move",
  "description": "Apply exactly one cube move in standard notation and return the resulting state. Invalid tokens are rejected and do not change the cube or use any of the move budget.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "move": {
        "type": "string",
        "description": "One move token, e.g. \"R\", \"U'\", \"F2\", \"Rw\", \"r2\", \"M'\", \"y\", \"x2\"."
      }
    },
    "required": ["move"],
    "additionalProperties": false
  }
}
```

### One call = one move

**Recommendation: yes, hard default, one `make_move` call applies exactly one move token.**
Reasons: it matches the user's own framing of the loop ("LLM sends one move... gets the new text
state back"); it keeps validation atomic (a call either fully succeeds or changes nothing, no
partial-application edge cases); it keeps the JSONL log one row per move, which §6's metrics rely
on directly; and it keeps the system prompt's control flow trivial to state ("call the tool, read
the result, call the tool again").

Cheap optional extension, **off by default**: a `CUBE_ALLOW_SEQUENCES=1` server env var could let
`move` contain a space-separated sequence (e.g. `"R U R' U'"`), validated token-by-token before
any are applied (all-or-nothing — if any token is invalid, none are applied and the whole
sequence is reported as the single invalid token that failed), consuming one budget slot per
token that *is* applied. This is a config flag, not a default, because it complicates the "one
line = one move" invariant the log format depends on; only build it if the orchestrator asks.

### Result text

All results share the state+footer shape from §1. `{net}` = the full rendered block from §1
(headers + grids); `{moves_used}` / `{move_budget}` / `{uniform_count}` as defined there.

**`get_state`, or `make_move` success (not yet solved):**
```
Applied: R

{net}

Moves used: {moves_used}/{move_budget}
Uniform stickers: {uniform_count}/54
Status: IN_PROGRESS — in progress
```
(`get_state` omits the leading `Applied: {move}` line — everything else is identical.)

**`make_move` with an unrecognized token** (state unchanged, budget not consumed):
```
Invalid move: "{input}" is not a recognized move token. No changes made.

Valid tokens: face turns U D R L F B; wide Uw Dw Rw Lw Fw Bw (or lowercase u d r l f b);
slices M E S; rotations x y z — each optionally followed by ' (counterclockwise) or 2
(180 degrees, 2' also accepted).

{net}

Moves used: {moves_used}/{move_budget}
Uniform stickers: {uniform_count}/54
Status: IN_PROGRESS — in progress
```

**`make_move` that solves the cube:**
```
Applied: R2

{net}

Moves used: {moves_used}/{move_budget}
Uniform stickers: 54/54
Status: SOLVED — cube solved in {moves_used} moves. Stop calling tools and report success.
```
Solved is checked *before* checking the budget: if the move that exhausts the budget also solves
the cube, report `SOLVED`, not `OUT_OF_MOVES`.

**`make_move` that exhausts the budget without solving:**
```
Applied: L'

{net}

Moves used: {moves_used}/{move_budget}
Uniform stickers: {uniform_count}/54
Status: OUT_OF_MOVES — move budget exhausted before solving. Stop calling tools and report the result.
```

**`make_move` called again after the game has already ended** (defensive — the system prompt
tells the model to stop, but the server must not silently accept moves past the terminal state):
```
Game already over (SOLVED after {moves_used} moves). No further moves accepted.
```
(or `OUT_OF_MOVES after {moves_used} moves` — no state re-render, short by design, since the
model already saw the final board on the previous turn.) `get_state` keeps working normally after
game-over and keeps returning the final board + terminal status — it's read-only, so there's no
reason to special-case it.

### Server startup config (env vars, set by the runner before spawning the server)

| Env var | Meaning |
|---|---|
| `CUBE_SCRAMBLE_SEED` | int, required. RNG seed for the scramble. |
| `CUBE_SCRAMBLE_DEPTH` | int, or the literal string `random`. `N` → `scramble N` (N-move walk); `random` → uniform random-state scramble. |
| `CUBE_MOVE_BUDGET` | int, required. Max `make_move` calls before `OUT_OF_MOVES`. |
| `CUBE_LOG_PATH` | file path. Where the JSONL log (§6) is written. Defaults to `logs/<timestamp>.jsonl` if unset. |
| `CUBE_GAME_ID` | optional string. Embedded in the log's `start` event; defaults to a generated id if unset. |

The scramble sequence is computed once at process start, applied to an internal solved cube, and
**never appears in any tool result** — it is written only to the server-side JSONL log (§6), which
the LLM's process cannot read (the runner launches `claude -p` from an empty temp cwd per the
orchestrator's architecture note).

Illustrative — not authoritative on exact `claude -p` flags, confirm against `claude -p --help` —
MCP config the runner would pass via `--mcp-config` / `--strict-mcp-config`. Paths must be
absolute: `claude -p` runs from an empty temp cwd (per the orchestrator's architecture note), so
any relative path here would resolve against the wrong directory.
```json
{
  "mcpServers": {
    "cube": {
      "command": "/Users/fin/Desktop/orchbrain/rubiks-llm/.venv/bin/python",
      "args": ["/Users/fin/Desktop/orchbrain/rubiks-llm/mcp_server.py"],
      "env": {
        "CUBE_SCRAMBLE_SEED": "3",
        "CUBE_SCRAMBLE_DEPTH": "8",
        "CUBE_MOVE_BUDGET": "45",
        "CUBE_LOG_PATH": "/Users/fin/Desktop/orchbrain/rubiks-llm/logs/depth8_seed3.jsonl"
      }
    }
  }
}
```
With server name `cube`, Claude Code exposes the tools as `mcp__cube__get_state` and
`mcp__cube__make_move`; restrict `--allowedTools` to just those two so the model can't reach for
Bash/Read/WebFetch/etc. The initial `claude -p` prompt should *not* embed the board text itself —
tell the model to call `get_state` first, so the server stays the single source of truth for
rendering (§1's renderer is never duplicated in the runner).

---

## 3. Game rules

- **Move budget**: required per game (`CUBE_MOVE_BUDGET`), no built-in default — see §6 for the
  suggested per-difficulty values used in evaluation. There is no minimum/maximum enforced by the
  protocol itself.
- **Rotations (`x y z`) and slices (`M E S`) count toward the budget**, same as any other move.
  Reasoning: every `make_move` call is a turn by definition of the protocol in §2; if rotations
  were free, a model could pad turns indefinitely without ever gaming that in the *solve*, but it
  would break the log's "one row = one move, moves_used increments monotonically with a clean
  cap" invariant, and it removes a cheap incentive for the model to reason efficiently instead of
  re-orienting itself repeatedly. Make this a config flag only if evaluation shows models get
  unfairly punished for legitimate re-orientation — not built preemptively.
- **Invalid moves (unrecognized tokens) do not consume budget.** They're rejected before being
  "spent" — see §2. They are still logged and counted (`invalid_move_count`, §6) so a model that
  can't produce valid notation shows up clearly in the metrics without being penalized twice.
- **Scramble is always hidden from the LLM.** It is applied server-side before the LLM's first
  tool call and never appears in any tool result, system prompt, or user prompt — only in the
  server-side JSONL log. This was flagged in the brief as the orchestrator's lean ("otherwise the
  LLM can just invert it") and nothing here contradicts it.
- **No `give_up` tool.** The model simply stops calling tools when it chooses to (or is told to,
  at `SOLVED`/`OUT_OF_MOVES`) and emits a final text response; `claude -p` ends the turn when no
  more tool calls are made. Three terminal outcomes, determined by the runner from the log (§6):
  `solved`, `exhausted` (budget ran out), `abandoned` (model stopped calling tools on its own
  before either of those — the log simply has no `end` event).
- **What's shown at game start**: nothing about the scramble. The `claude -p` user prompt is a
  fixed instruction (see §4) telling the model to call `get_state` first; the *result* of that
  call is the first time the model sees the (scrambled) board.

---

## 4. Solver system prompt

Full text, for `claude -p --append-system-prompt`. Written for the actual runtime: the model must
keep calling tools turn after turn with no user in the loop, and must stop cleanly at a terminal
state instead of continuing or asking questions nobody will answer.

```
You are solving a 3x3 Rubik's Cube through two tools: get_state and make_move. There is no
human in the loop — you must keep working autonomously, turn after turn, until the cube is
solved or you run out of moves. Do not ask questions or wait for input; none will come.

READING THE BOARD
The board is shown as an unfolded cube net: the Up face on top, Left/Front/Right/Back side by
side in the middle band (in that left-to-right order), Down face at the bottom. Each face is
printed as its own 3x3 grid of color letters, read left-to-right then top-to-bottom, exactly as
you'd see that face if you turned the cube to look straight at it with Up still on top (for the
Up face itself, read it from above with Back at the top of the grid and Front at the bottom; for
Down, read it from below with Front at the top of the grid and Back at the bottom).

Color letters: W=White Y=Yellow G=Green R=Red O=Orange B=Blue. These are sticker colors, not
face names — a face is only "solved" when its 3x3 grid is a single repeated letter.

Every state includes a footer:
  Moves used: X/Y          <- moves you've spent out of your total budget
  Uniform stickers: N/54   <- how many stickers already match their face's majority color
  Status: IN_PROGRESS / SOLVED / OUT_OF_MOVES

The cube starts scrambled. You are not told the scramble - call get_state first to see it.

MAKING MOVES
Call make_move with exactly one move token per call:
  Face turns:  U D R L F B            (clockwise, looking straight at that face)
  Wide turns:  Uw Dw Rw Lw Fw Bw  or lowercase  u d r l f b   (turns the outer 2 layers)
  Rotations:   x y z                  (x follows R, y follows U, z follows F - turns the whole cube)
  Slices:      M E S                  (M follows L, E follows D, S follows F - turns the middle layer)
  Modifiers:   append ' for counterclockwise, 2 (or 2') for a 180 degree turn.
  Examples: R, U', F2, Rw, r2, M', y, x2

An unrecognized token is rejected with an error and changes nothing - it does not use up any of
your move budget, so a rejected move just costs you a turn's worth of time, not progress. Prefer
getting the notation right the first time.

YOUR LOOP
1. Call get_state to see the current board (only needed once, at the start, or whenever you are
   not fully sure you're tracking the cube correctly - it's free and doesn't count against your
   budget).
2. Decide on one move that makes progress toward solved (all 6 faces uniform).
3. Call make_move with that one move token.
4. Read the resulting state and footer. Check it against what you expected before you made the
   move. If it doesn't match, the returned state is always right and your own tracking was
   wrong - update your mental model to match it rather than continuing to plan from your old
   prediction. If Status is still IN_PROGRESS, go back to step 2.
5. If Status is SOLVED or OUT_OF_MOVES, stop calling tools immediately and write one short
   final message reporting the outcome (solved / ran out of moves) and the move count. Do not
   call make_move again after this - further calls will be rejected.

Think step by step about cube state before each move if it helps you, but every turn must end
in exactly one make_move (or, on your very first turn, one get_state) call - never end a turn
with only prose and no tool call unless the game has just ended.
```

---

## 5. CLI for humans

`cli.py` is a plain REPL over the same `cube.py` engine and the same `render_state` used by the
MCP server — no move budget, no hidden scramble, no logging. It's for humans exploring/debugging
the engine directly, separate from the LLM harness in §2.

| Command | Effect |
|---|---|
| `scramble` | Uniform random-state scramble. Prints the resulting state. |
| `scramble N` | Random N-move scramble (no consecutive same-face moves). Prints the resulting state. |
| `reset` | Return to solved. Prints the resulting state. |
| `show` | Reprint the current state without changing it. |
| `<move>` | Apply one move in standard notation (e.g. `R`, `U2`, `Rw'`, `x`). Prints the resulting state, or an error if the token isn't recognized. |
| `help` | Print the command list and the notation reference (same wording as §4's notation block). |
| `quit` / `exit` | Exit the REPL. |

Output reuses §1's block exactly, with a footer trimmed to what applies outside a budgeted game
(no budget, so no `Moves used: X/Y` line):
```
> R
Applied: R

              U (Up)
              W W G
              W W G
              W W G

  L (Left)    F (Front)   R (Right)   B (Back)
  O O O       G G Y       R R R       W B B
  O O O       G G Y       R R R       W B B
  O O O       G G Y       R R R       W B B

              D (Down)
              Y Y B
              Y Y B
              Y Y B

Uniform stickers: 42/54
Status: IN_PROGRESS

> Rw3
Invalid move: "Rw3" is not a recognized move token. No changes made.

Valid tokens: face turns U D R L F B; wide Uw Dw Rw Lw Fw Bw (or lowercase u d r l f b);
slices M E S; rotations x y z - each optionally followed by ' (counterclockwise) or 2
(180 degrees, 2' also accepted).
```
`scramble`/`scramble N`/`reset`/`show` all print the same block (net + `Uniform stickers: N/54` +
`Status:`), no `Applied:` line since no single move was applied.

---

## 6. Evaluation

The runner (suggested filename `run_eval.py`) runs one `claude -p` invocation per game, across a
difficulty ladder, and reads the MCP server's JSONL log as ground truth — it does not re-derive
metrics from the model's chat transcript.

### Difficulty ladder (defaults — tune after seeing real pass rates)

| Difficulty | `CUBE_SCRAMBLE_DEPTH` | `CUBE_MOVE_BUDGET` | Repeats |
|---|---|---|---|
| depth_1 | 1 | 10 | 5 |
| depth_2 | 2 | 15 | 5 |
| depth_3 | 3 | 20 | 5 |
| depth_5 | 5 | 30 | 5 |
| depth_8 | 8 | 45 | 5 |
| depth_12 | 12 | 60 | 5 |
| random_state | `random` | 100 | 5 |

Budgets are generous on purpose: an LLM solving beginner-method style is expected to be far less
efficient than an optimal solver, and a too-tight budget mostly measures "ran out of room" rather
than "couldn't solve it." 5 repeats per rung with seeds `0..4` is a cheap default (35 games for a
full sweep); use the same 5 seeds across every rung so, for the depth rungs, each repeat's shorter
scrambles are literal prefixes of that repeat's longer ones (if the N-move scramble generator is a
seeded random walk, seed `k`'s first 3 moves are the same for depth_3 and depth_12) — not required
for correctness, just tidy for comparing across rungs.

### Safety caps and claude's own result (runner-side, not the server log)

Two independent safety caps bound each `claude -p` invocation and can cut a game off before the
model reaches `SOLVED`/`OUT_OF_MOVES` on its own — claude v2.1.269 has **no `--max-turns` flag**,
so these are the only two caps, and neither lives in the MCP server:
- `claude -p --max-budget-usd` (default `5`, i.e. $5/game).
- A runner-enforced per-game wall-clock timeout (default `1800`s / 30 min), implemented outside
  `claude -p` itself (e.g. the runner kills the subprocess if it outlives the timeout).

The runner also captures claude's own end-of-run result for each invocation (pass
`--output-format json`; confirm the exact result-object field names against the installed CLI,
v2.1.269, via `claude -p --help`/docs before hardcoding them — cost, wall-clock duration, and
number of turns are the fields to capture, referred to below as `cost_usd` / `duration_ms` /
`num_turns` illustratively) and merges it with the server's JSONL-derived fields into one
per-game record.

### Metrics (per game, computed by the runner from one game's JSONL log plus claude's own result)

- `solved: bool`
- `moves_used: int`
- `invalid_move_count: int`
- `solved_sticker_fraction: float` — the final `Uniform stickers / 54` value, using the same
  orientation-independent metric as §1's footer (not a comparison against one fixed reference
  coloring).
- `outcome: "solved" | "exhausted" | "abandoned"` — `abandoned` means the log has no `end` event
  (the model stopped calling tools on its own before a terminal state was reached; the server
  can't observe process exit, so this is inferred from the log's shape, not written by the
  server itself).
- `cost_usd: float`, `duration_ms: int`, `num_turns: int` — from claude -p's own result JSON for
  this invocation (see above).
- `cutoff_reason: "timeout" | "max_budget_usd" | "claude_error" | null` — set only when one of the
  runner's own safety caps (or an unrelated claude -p error) ended the process, as opposed to the
  model reaching a natural stopping point. `"timeout"` if the runner's wall-clock timeout killed
  it; `"max_budget_usd"` if `--max-budget-usd` cut it off; `"claude_error"` if `claude -p` exited
  with an error unrelated to those two caps; `null` otherwise. This is what tells an `outcome:
  "abandoned"` game apart into two very different cases: the model quietly stopped calling tools
  on its own (`cutoff_reason: null`) versus the runner forcibly killed a run that was still going
  (`cutoff_reason` set).

### JSONL log format (written by the MCP server, one file per game, one JSON object per line)

```json
{"event": "start", "ts": "2026-09-11T15:30:00Z", "game_id": "depth8_seed3", "scramble_depth": 8, "scramble_seed": 3, "move_budget": 45, "scramble_moves": ["R", "U'", "F2", "..."], "initial_state": "WWG...B"}
{"event": "call", "ts": "2026-09-11T15:30:02Z", "turn": 0, "tool": "get_state", "input": {}, "outcome": "ok", "moves_used": 0, "state_after": "WWG...B"}
{"event": "call", "ts": "2026-09-11T15:30:04Z", "turn": 1, "tool": "make_move", "input": {"move": "R"}, "outcome": "ok", "moves_used": 1, "state_after": "WWG...B"}
{"event": "call", "ts": "2026-09-11T15:30:06Z", "turn": 2, "tool": "make_move", "input": {"move": "Rw3"}, "outcome": "invalid", "error": "not a recognized move token", "moves_used": 1, "state_after": "WWG...B"}
{"event": "call", "ts": "2026-09-11T15:30:40Z", "turn": 9, "tool": "make_move", "input": {"move": "R2"}, "outcome": "solved", "moves_used": 9, "state_after": "WWW...B"}
{"event": "end", "ts": "2026-09-11T15:30:41Z", "result": "solved", "moves_used": 9, "invalid_move_count": 1, "solved_sticker_fraction": 1.0, "final_state": "WWW...B"}
```
`outcome` on a `call` line ∈ `ok | invalid | solved | exhausted | already_over`. `scramble_moves`
and `initial_state` in the `start` event are server-log-only — never sent to the LLM (§3). States
are logged in the compact 54-character form (§1), not the pretty-printed net, to keep the log
small and machine-parseable; regenerate the net from the compact string for human review with
§1's renderer. A game with no `end` line is `abandoned` by definition (see Metrics above).

### Results summary (written by the runner after a full ladder sweep, e.g. `logs/summary_<run_id>.json`)

```json
{
  "run_id": "2026-09-11-153000",
  "ladder": [
    {
      "difficulty": "depth_1",
      "scramble_depth": 1,
      "move_budget": 10,
      "games": 5,
      "outcomes": {"solved": 5, "exhausted": 0, "abandoned": 0},
      "solved_rate": 1.0,
      "avg_moves_used_when_solved": 3.2,
      "avg_invalid_move_count": 0.0,
      "avg_solved_sticker_fraction": 1.0,
      "per_game": [
        {
          "game_id": "depth1_seed0",
          "seed": 0,
          "outcome": "solved",
          "moves_used": 3,
          "invalid_move_count": 0,
          "solved_sticker_fraction": 1.0,
          "cost_usd": 0.08,
          "duration_ms": 14200,
          "num_turns": 4,
          "cutoff_reason": null
        }
      ]
    }
  ]
}
```
`avg_moves_used_when_solved` is averaged only over solved games (undefined/`null` if none solved
in that rung); `avg_solved_sticker_fraction` and `avg_invalid_move_count` are averaged over all
games in the rung. `per_game` holds one record per repeat (§6's Metrics list, one-to-one) so a
run can be inspected at the individual-game level, not just the rung aggregate. The runner should
also print a plain-text table of the aggregate rows to stdout,
e.g.:
```
difficulty    games  solved  solved_rate  avg_moves(solved)  avg_invalid  avg_sticker_frac
depth_1       5      5       1.00         3.2                0.0         1.00
depth_2       5      5       1.00         5.8                0.2         1.00
random_state  5      2       0.40         71.5               3.4         0.81
```
