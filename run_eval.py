"""Evaluation runner (DESIGN.md §6): one headless `claude -p` game per rung and
seed, scored from the MCP server's JSONL logs.

Each game runs in a fresh empty temp dir with its own MCP config (absolute
paths), only the two cube tools (built-in tools off, no other MCP servers)
and two caps: claude's --max-budget-usd and a wall-clock timeout. Everything
lands in logs/<run_id>/: per game <id>.jsonl (server log), <id>.mcp.json,
<id>.stream.jsonl (claude's stream-json transcript) and <id>.claude.json (its
final result plus the model used), and summary.json for the whole run.

A sweep stops as soon as claude reports the account's usage limit; finish it
later with --resume <run_id>.

  .venv/bin/python run_eval.py --rungs depth_1 --repeats 1
  .venv/bin/python run_eval.py --resume 2026-09-11-231500
"""

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from statistics import mean

from cube import uniform_count

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"
PYTHON = ROOT / ".venv" / "bin" / "python"
SERVER = ROOT / "mcp_server.py"
SOLVER_PROMPT = (ROOT / "prompts" / "solver_system.txt").read_text().rstrip("\n")
USER_PROMPT = "Solve the cube. Start by calling get_state."
MAKE_MOVE = "mcp__cube__make_move"
ALLOWED_TOOLS = f"mcp__cube__get_state,{MAKE_MOVE}"
CLAUDE = shutil.which("claude") or "claude"

LADDER = {  # difficulty -> (CUBE_SCRAMBLE_DEPTH, CUBE_MOVE_BUDGET)
    "depth_1": (1, 10),
    "depth_2": (2, 15),
    "depth_3": (3, 20),
    "depth_5": (5, 30),
    "depth_8": (8, 45),
    "depth_12": (12, 60),
    "random_state": ("random", 100),
}
OUTCOMES = ("solved", "exhausted", "abandoned")
USAGE_LIMIT_TEXT = re.compile(r"\b(usage|session|rate) limit", re.IGNORECASE)

# Set by a parent Claude Code session. The solver must not inherit them: claude
# may refuse to start nested, and the messaging vars would let it reach the
# parent's peer-messaging socket.
NESTED_SESSION_VARS = {
    "CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "AI_AGENT",
    "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_BRIDGE_SESSION_ID", "CLAUDE_CODE_SSE_PORT",
    "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
}


def game_id(difficulty, seed):
    return f"{difficulty}_seed{seed}"


def mcp_config(game_id, depth, budget, seed, log_path) -> dict:
    """MCP config for one game. Absolute paths: claude runs from a temp dir."""
    return {"mcpServers": {"cube": {
        "type": "stdio",
        "command": str(PYTHON),
        "args": [str(SERVER)],
        "env": {
            "CUBE_SCRAMBLE_SEED": str(seed),
            "CUBE_SCRAMBLE_DEPTH": str(depth),
            "CUBE_MOVE_BUDGET": str(budget),
            "CUBE_LOG_PATH": str(Path(log_path).resolve()),
            "CUBE_GAME_ID": game_id,
        },
    }}}


def claude_command(config_path, max_usd, model=None, effort=None) -> list[str]:
    # The prompt sits right after -p: --mcp-config, --tools and --allowedTools
    # are variadic and would swallow a trailing positional argument.
    cmd = [CLAUDE, "-p", USER_PROMPT,
           "--output-format", "stream-json", "--verbose",
           "--mcp-config", str(config_path), "--strict-mcp-config",
           "--tools", "",
           "--allowedTools", ALLOWED_TOOLS,
           "--permission-prompts", "none",
           "--append-system-prompt", SOLVER_PROMPT,
           "--no-session-persistence",
           "--disable-slash-commands",
           "--max-budget-usd", f"{max_usd:g}"]
    if model:
        cmd += ["--model", model]
    if effort:
        cmd += ["--effort", effort]
    return cmd


def child_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in NESTED_SESSION_VARS}


def run_claude(cmd, timeout):
    """Run cmd in a fresh empty temp dir. Returns (stdout, stderr, returncode, timed_out)."""
    with tempfile.TemporaryDirectory(prefix="cube-game-") as cwd:
        # Own process group, so a timeout also kills the MCP server claude spawned.
        proc = subprocess.Popen(cmd, cwd=cwd, env=child_env(), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                start_new_session=True)
        try:
            out, err = proc.communicate(timeout=timeout)
            return out, err, proc.returncode, False
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = proc.communicate()
            return out, err, proc.returncode, True


def parse_stream(out) -> list[dict]:
    """The JSON events in claude's stream-json output."""
    events = []
    for line in out.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def parallel_move_batches(events) -> int:
    """Assistant turns that issued more than one make_move. Grouped by message
    id, because one API message can arrive as several stream events."""
    moves = {}
    for i, event in enumerate(events):
        if event.get("type") == "assistant":
            message = event.get("message") or {}
            key = message.get("id") or i
            moves[key] = moves.get(key, 0) + sum(
                block.get("type") == "tool_use" and block.get("name") == MAKE_MOVE
                for block in message.get("content") or [])
    return sum(n > 1 for n in moves.values())


def cutoff_reason(result, returncode, timed_out):
    """Why claude stopped, if a safety cap, the usage limit or an error ended the game."""
    if timed_out:
        return "timeout"
    if result is None:
        return "claude_error"
    if result.get("api_error_status") == 429 or (
            result.get("is_error") and USAGE_LIMIT_TEXT.search(str(result.get("result")))):
        return "usage_limit"
    # The values claude 2.1.269 reports when --max-budget-usd trips.
    if (result.get("subtype") == "error_max_budget_usd"
            or result.get("terminal_reason") == "budget_exhausted"):
        return "max_budget_usd"
    if returncode != 0 or result.get("is_error"):
        return "claude_error"
    return None


def game_metrics(log_path) -> dict:
    """Per-game metrics from the server's JSONL log, the ground truth."""
    path = Path(log_path)
    events = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    start = next((e for e in events if e["event"] == "start"), None)
    calls = [e for e in events if e["event"] == "call"]
    end = next((e for e in events if e["event"] == "end"), None)
    if end:
        final = end["final_state"]
    elif calls:
        final = calls[-1]["state_after"]
    else:
        final = start["initial_state"] if start else None
    outcome = end["result"] if end else "abandoned"
    return {
        "outcome": outcome,
        "solved": outcome == "solved",
        "moves_used": calls[-1]["moves_used"] if calls else 0,
        "invalid_move_count": sum(c["outcome"] == "invalid" for c in calls),
        "solved_sticker_fraction": round(uniform_count(final) / 54, 4) if final else None,
    }


def model_used(events):
    """The model that played: the init event's, else the costliest in modelUsage
    (claude also makes small side calls to a cheaper model)."""
    init = next((e for e in events if e.get("subtype") == "init"), {})
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    usage = result.get("modelUsage") or {}
    return init.get("model") or max(usage, key=lambda m: usage[m].get("costUSD") or 0,
                                    default=None)


def run_game(run_dir, difficulty, seed, args) -> dict:
    """Play one game with claude, save its files and return its record."""
    depth, budget = LADDER[difficulty]
    gid = game_id(difficulty, seed)
    log_path = run_dir / f"{gid}.jsonl"
    log_path.unlink(missing_ok=True)  # a rerun under --resume starts a fresh log
    config_path = run_dir / f"{gid}.mcp.json"
    config_path.write_text(json.dumps(mcp_config(gid, depth, budget, seed, log_path), indent=2))
    cmd = claude_command(config_path, args.max_usd, args.model, args.effort)
    out, err, returncode, timed_out = run_claude(cmd, args.timeout)
    (run_dir / f"{gid}.stream.jsonl").write_text(out)
    events = parse_stream(out)
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    (run_dir / f"{gid}.claude.json").write_text(json.dumps(
        {"returncode": returncode, "timed_out": timed_out, "model": model_used(events),
         "parallel_move_batches": parallel_move_batches(events), "result": result,
         "stderr": err}, indent=2))
    return game_record(run_dir, difficulty, seed)


def game_record(run_dir, difficulty, seed) -> dict:
    """A game's record, rebuilt from its server log and claude.json."""
    gid = game_id(difficulty, seed)
    path = run_dir / f"{gid}.claude.json"
    claude = json.loads(path.read_text()) if path.exists() else {}
    result = claude.get("result") or {}
    return {"game_id": gid, "seed": seed, **game_metrics(run_dir / f"{gid}.jsonl"),
            "parallel_move_batches": claude.get("parallel_move_batches"),
            "model": claude.get("model"),
            "cost_usd": result.get("total_cost_usd"),
            "duration_ms": result.get("duration_ms"),
            "num_turns": result.get("num_turns"),
            "cutoff_reason": cutoff_reason(claude.get("result"), claude.get("returncode"),
                                           claude.get("timed_out")) if claude else None}


def played(run_dir, difficulty, seed):
    """(record, None) for a game that counts, or (None, reason) for one to (re)run."""
    gid = game_id(difficulty, seed)
    if (not (run_dir / f"{gid}.claude.json").exists()
            and game_metrics(run_dir / f"{gid}.jsonl")["outcome"] == "abandoned"):
        return None, "not_started"
    record = game_record(run_dir, difficulty, seed)
    if record["cutoff_reason"] == "usage_limit":
        return None, "usage_limit"
    return record, None


def _avg(values):
    values = list(values)
    return round(mean(values), 4) if values else None


def rung_summary(difficulty, games) -> dict:
    depth, budget = LADDER[difficulty]
    solved = [g for g in games if g["outcome"] == "solved"]
    return {
        "difficulty": difficulty,
        "scramble_depth": depth,
        "move_budget": budget,
        "games": len(games),
        "outcomes": {o: sum(g["outcome"] == o for g in games) for o in OUTCOMES},
        "solved_rate": round(len(solved) / len(games), 4),
        "avg_moves_used_when_solved": _avg(g["moves_used"] for g in solved),
        "avg_invalid_move_count": _avg(g["invalid_move_count"] for g in games),
        "avg_solved_sticker_fraction": _avg(g["solved_sticker_fraction"] for g in games
                                            if g["solved_sticker_fraction"] is not None),
        "per_game": games,
    }


def write_summary(run_dir, config) -> dict:
    """Recompute summary.json over every game in the run's plan."""
    ladder, not_run = [], []
    for rung in config["rungs"]:
        games = []
        for seed in config["seeds"]:
            record, reason = played(run_dir, rung, seed)
            if record:
                games.append(record)
            else:
                not_run.append({"game_id": game_id(rung, seed), "reason": reason})
        if games:
            ladder.append(rung_summary(rung, games))
    models = sorted({g["model"] for r in ladder for g in r["per_game"] if g["model"]})
    summary = {"run_id": run_dir.name, "config": {**config, "models_used": models},
               "ladder": ladder, "not_run": not_run}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def format_table(ladder) -> str:
    def num(value, digits):
        return "-" if value is None else f"{value:.{digits}f}"

    rows = [("difficulty", "games", "solved", "solved_rate", "avg_moves(solved)",
             "avg_invalid", "avg_sticker_frac")]
    for r in ladder:
        rows.append((r["difficulty"], str(r["games"]), str(r["outcomes"]["solved"]),
                     num(r["solved_rate"], 2), num(r["avg_moves_used_when_solved"], 1),
                     num(r["avg_invalid_move_count"], 1),
                     num(r["avg_solved_sticker_fraction"], 2)))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip()
             for row in rows]
    cut = [g for r in ladder for g in r["per_game"] if g["cutoff_reason"]]
    if cut:
        lines += ["", "Cut off by a safety cap or error:"]
        lines += [f"  {g['game_id']}: {g['cutoff_reason']}" for g in cut]
    return "\n".join(lines)


def main(argv=None) -> dict:
    parser = argparse.ArgumentParser(description="Run LLM cube-solving games with claude -p.")
    parser.add_argument("--rungs", nargs="+", choices=list(LADDER), default=list(LADDER),
                        help="difficulty rungs to run (default: all)")
    parser.add_argument("--repeats", type=int, default=5,
                        help="games per rung, with seeds 0..N-1 (default 5)")
    parser.add_argument("--seeds", nargs="+", type=int,
                        help="explicit seeds; overrides --repeats")
    parser.add_argument("--model", help="passed to claude --model (default: the CLI's default)")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"],
                        help="passed to claude --effort (default: unset)")
    parser.add_argument("--max-usd", type=float, default=5.0,
                        help="claude --max-budget-usd per game (default 5.00)")
    parser.add_argument("--timeout", type=float, default=1800,
                        help="wall-clock seconds per game (default 1800)")
    parser.add_argument("--resume", metavar="RUN_ID",
                        help="finish logs/RUN_ID with its original settings: run only the games "
                             "that never started or were stopped by the usage limit")
    args = parser.parse_args(argv)

    if args.resume:
        run_dir = LOGS / args.resume
        config = json.loads((run_dir / "summary.json").read_text())["config"]
    else:
        run_dir = LOGS / datetime.now().strftime("%Y-%m-%d-%H%M%S")
        run_dir.mkdir(parents=True)
        seeds = args.seeds if args.seeds is not None else list(range(args.repeats))
        config = {"rungs": args.rungs, "seeds": seeds, "model": args.model,
                  "effort": args.effort, "max_usd": args.max_usd, "timeout_s": args.timeout}
        write_summary(run_dir, config)  # records the plan for --resume
    opts = argparse.Namespace(model=config["model"], effort=config["effort"],
                              max_usd=config["max_usd"], timeout=config["timeout_s"])
    todo = [(rung, seed) for rung in config["rungs"] for seed in config["seeds"]
            if played(run_dir, rung, seed)[0] is None]
    for i, (rung, seed) in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {game_id(rung, seed)} ...", flush=True)
        g = run_game(run_dir, rung, seed, opts)
        print(f"    {g['outcome']}: {g['moves_used']} moves, {g['invalid_move_count']} "
              f"invalid, {g['parallel_move_batches']} parallel batches, ${g['cost_usd']}, "
              f"{g['duration_ms']} ms, {g['model']}, cutoff {g['cutoff_reason']}", flush=True)
        write_summary(run_dir, config)  # after every game, so a crash keeps the results
        if g["cutoff_reason"] == "usage_limit":
            print("\nClaude usage limit reached: stopping the sweep.")
            break
    summary = write_summary(run_dir, config)
    print()
    print(format_table(summary["ladder"]))
    if summary["not_run"]:
        print("\nNot run: " + ", ".join(f"{g['game_id']} ({g['reason']})"
                                        for g in summary["not_run"]))
        print(f"Resume with: .venv/bin/python run_eval.py --resume {run_dir.name}")
    print(f"\nLogs and summary: {run_dir}")
    return summary


if __name__ == "__main__":
    main()
