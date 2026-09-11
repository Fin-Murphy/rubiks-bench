# Rubik's cube LLM solver

A 3x3 Rubik's cube simulator with a text interface, plus a harness in which an
LLM (headless Claude Code) tries to solve a scrambled cube one move at a time
through an MCP server. Design: `docs/DESIGN.md`. Background: `docs/RESEARCH.md`.

| File | What it is |
|---|---|
| `cube.py` | Engine, stdlib only: 54-facelet state (Kociemba order), full move notation, scrambles, the text net |
| `game.py` | One budgeted game: rules, tool result text, JSONL log |
| `mcp_server.py` | MCP stdio server `cube` with the tools `get_state` and `make_move` |
| `cli.py` | Interactive REPL for humans |
| `run_eval.py` | Runs `claude -p` games over a difficulty ladder and summarizes them |
| `prompts/solver_system.txt` | The solver system prompt (DESIGN.md §4, verbatim) |
| `tests/` | pytest suite |

## Setup

Python 3.10 or newer (developed on 3.14). macOS or Linux: the runner and the
MCP configs below use `.venv/bin/python`.

    python3 -m venv .venv
    .venv/bin/pip install -r requirements-dev.txt

Create the venv at exactly `.venv/` in the repo root: `run_eval.py` launches the
MCP server with `.venv/bin/python`.

`requirements.txt` holds the one runtime dependency, `mcp`, which only the
server needs. The engine and the CLI use the standard library alone.

To run Claude models you also need the [Claude Code](https://claude.com/claude-code)
CLI (`claude`), installed and logged in. Games run on that login, so they count
against your Claude plan's usage limits. With `ANTHROPIC_API_KEY` set, they are
billed to the API instead.

## Tests

    .venv/bin/python -m pytest

`tests/test_crossval.py` checks the engine against pycuber and is skipped if
pycuber isn't installed.

## Play in the terminal

    .venv/bin/python cli.py

Commands: `scramble`, `scramble N`, `reset`, `show`, `help`, `quit`, or one
move per line: face turns `U D R L F B`, wide turns `Uw`..`Bw` or
`u d r l f b`, slices `M E S`, rotations `x y z`, each optionally followed by
`'`, `2` or `2'`.

This prints exactly the net the model sees, so it's the quickest way to get a
feel for the representation.

## The MCP server

`mcp_server.py` scrambles once at startup and serves one game over stdio. It
reads these env vars:

| Variable | Meaning |
|---|---|
| `CUBE_SCRAMBLE_SEED` | int, required |
| `CUBE_SCRAMBLE_DEPTH` | number of random face turns, or `random` for a uniform random-state scramble (the default) |
| `CUBE_MOVE_BUDGET` | int, required: how many moves `make_move` accepts |
| `CUBE_LOG_PATH` | JSONL log file (default `logs/<timestamp>.jsonl`) |
| `CUBE_GAME_ID` | id written to the log (default `game_<timestamp>`) |

`get_state` is free. `make_move` takes exactly one move token; an invalid token
is rejected without changing the cube or using budget. The scramble goes only
to the log, never into a tool result.

## Watch a model play

To see what the model is shown and what it sends back, move by move, run a
game in an interactive Claude Code session.

1. From the repo root, write an MCP config for one game. Paths must be
   absolute, because claude runs from another directory. `$PWD` fills them in:

        mkdir -p ~/cube-play
        cp prompts/solver_system.txt ~/cube-play/
        cat > ~/cube-play/cube.mcp.json <<EOF
        {"mcpServers": {"cube": {
          "type": "stdio",
          "command": "$PWD/.venv/bin/python",
          "args": ["$PWD/mcp_server.py"],
          "env": {
            "CUBE_SCRAMBLE_SEED": "0",
            "CUBE_SCRAMBLE_DEPTH": "5",
            "CUBE_MOVE_BUDGET": "30",
            "CUBE_LOG_PATH": "$PWD/logs/manual/depth_5_seed0.jsonl"
          }
        }}}
        EOF

   It copies the solver prompt into the play folder too, so step 2 needs
   nothing from the repo.

2. Start claude with only the two cube tools. Run it from that empty folder
   rather than the repo, so the solver has nothing else to look at:

        cd ~/cube-play
        claude --mcp-config cube.mcp.json --strict-mcp-config --tools "" \
          --allowedTools "mcp__cube__get_state,mcp__cube__make_move" \
          --append-system-prompt "$(cat solver_system.txt)"

   Add `--model <name>` or `--effort <level>` to try other models and effort
   levels.

3. Type `Solve the cube. Start by calling get_state.`

4. Watch. Each tool call shows the move the model sent, e.g.
   `make_move(move: "R'")`, along with any reasoning text before it. Tool
   results are collapsed; press ctrl+o to expand the transcript and see the
   full net and footer the model got back. The server log (`CUBE_LOG_PATH`)
   records every call with the resulting state.

The server scrambles once, so each session is one game. For a new scramble,
change `CUBE_SCRAMBLE_SEED` or `CUBE_SCRAMBLE_DEPTH` and restart claude.

## Evaluation

    .venv/bin/python run_eval.py --rungs depth_1 --repeats 1   # one quick game
    .venv/bin/python run_eval.py --repeats 1                    # one game per rung
    .venv/bin/python run_eval.py --resume <run_id>              # finish a stopped sweep

Options: `--rungs` (any of depth_1 depth_2 depth_3 depth_5 depth_8 depth_12
random_state), `--repeats N` (seeds 0..N-1, default 5), `--seeds` (explicit
list), `--model`, `--effort`, `--max-usd` (claude's `--max-budget-usd` per
game, default 5), `--timeout` (seconds per game, default 1800) and
`--resume RUN_ID`.

The ladder (scramble depth and move budget per rung) is `LADDER` in
`run_eval.py`:

| Rung | Scramble | Move budget |
|---|---|---|
| depth_1 | 1 move | 10 |
| depth_2 | 2 moves | 15 |
| depth_3 | 3 moves | 20 |
| depth_5 | 5 moves | 30 |
| depth_8 | 8 moves | 45 |
| depth_12 | 12 moves | 60 |
| random_state | uniform random state | 100 |

Each game runs `claude -p` in a fresh, empty temp directory with:

- only our MCP server (`--mcp-config` plus `--strict-mcp-config`) and no
  built-in tools (`--tools ""`), so the model sees exactly
  `mcp__cube__get_state` and `mcp__cube__make_move`;
- those two tools pre-approved (`--allowedTools`), with every other permission
  prompt denied automatically (`--permission-prompts none`);
- no slash commands and no saved session;
- the solver prompt appended to the system prompt, and a fixed user prompt that
  never contains the board;
- a dollar cap (`--max-budget-usd`) and a wall-clock timeout. Claude checks the
  cap between API calls, so a game can overshoot it by one call's cost.

Results go to `logs/<run_id>/`:

- `<game_id>.jsonl`: the server's log, which is the ground truth for scoring
- `<game_id>.mcp.json`: the MCP config used
- `<game_id>.stream.jsonl`: claude's full stream-json transcript (the model's
  messages and tool calls)
- `<game_id>.claude.json`: claude's final result (cost, duration, turns,
  errors), the model that actually ran, and `parallel_move_batches` (turns in
  which the model sent more than one `make_move` at once)
- `summary.json`: the run's settings, per-rung aggregates, per-game records and
  any games not run; rewritten after every game

The runner prints the DESIGN.md §6 table and lists any games cut off by the
timeout, the dollar cap or a claude error.

To follow a game while it runs, tail its transcript or its server log:

    tail -f logs/<run_id>/<game_id>.stream.jsonl
    tail -f logs/<run_id>/<game_id>.jsonl

`claude -p` runs on your Claude login. If claude reports the account's usage
limit, the sweep stops at once. That game doesn't count; `summary.json` lists
it and the remaining games under `not_run`. `--resume <run_id>` later reruns
just those games, with the run's original settings.

### Comparing models

- Use the same seeds and the same ladder for every model. A seed fixes the
  scramble, and for the depth rungs, shorter scrambles are prefixes of longer
  ones for the same seed.
- Pass `--model` for each run. Read the model that actually played from
  `config.models_used` in `summary.json`, not from the flag.
- Compare `solved_rate` per rung first, then `avg_solved_sticker_fraction`
  (how close unsolved games got), `avg_invalid_move_count` (notation errors)
  and `avg_moves_used_when_solved` (efficiency).
- Deep rungs cost more: every result carries the full net, so context grows
  with each move.

### Known confound: your CLAUDE.md

Claude Code loads your personal `~/.claude/CLAUDE.md` into the solver's
context in both the runner and interactive games. The flags that would drop it
either need an API key (`--bare`) or also drop the cube server
(`--safe-mode`). If your CLAUDE.md has instructions that conflict with
autonomous play, such as "ask when uncertain", keep that in mind when reading
results, or run the benchmark from an account without one.

## Testing a model that isn't Claude

The benchmark is the server's rules and log, not Claude Code. There are two
ways to put another model on it.

**Any MCP client.** Launch `mcp_server.py` with the env vars above from your
agent framework's MCP support. Give the model `prompts/solver_system.txt` as
its system prompt and `Solve the cube. Start by calling get_state.` as the
user message. Then score the log (below).

**Your own loop, no MCP.** `game.Game` is the same game the server runs, as a
plain Python class. Expose `get_state` and `make_move` as your model's
function-calling tools, so the solver prompt applies unchanged. The core loop
from the repo root:

    from pathlib import Path
    from game import Game
    from run_eval import LADDER, game_metrics

    SYSTEM = Path("prompts/solver_system.txt").read_text()
    depth, budget = LADDER["depth_5"]
    log = "logs/mymodel/depth_5_seed0.jsonl"
    game = Game(seed=0, depth=depth, budget=budget, log_path=log, game_id="depth_5_seed0")

    observation = game.get_state()
    for _ in range(budget * 3):  # cap turns: invalid moves don't use budget
        move = my_model(SYSTEM, observation)  # your code: one move token, or None to stop
        if move is None:
            break
        observation = game.make_move(move)
        if game.result:  # "solved" or "exhausted"
            break

    print(game_metrics(log))

`game_metrics` scores the log exactly as `run_eval.py` does: outcome
(`solved`, `exhausted`, or `abandoned` if the model stopped early),
`moves_used`, `invalid_move_count` and `solved_sticker_fraction`. Use one log
file per game, and the ladder's seeds and budgets, to keep results comparable
with runner sweeps.
