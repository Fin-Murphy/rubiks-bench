"""The eval runner (DESIGN.md §6), with a fake claude standing in for the real one."""

import argparse
import json
import stat
from pathlib import Path

import pytest

import run_eval
from game import Game

ROOT = Path(__file__).resolve().parent.parent
OPTS = argparse.Namespace(max_usd=5.0, model=None, effort=None, timeout=20)
MOVE, STATE = "mcp__cube__make_move", "mcp__cube__get_state"
INIT = json.dumps({"type": "system", "subtype": "init", "model": "claude-test",
                   "tools": [STATE, MOVE]})
SUCCESS = json.dumps({"type": "result", "subtype": "success", "is_error": False,
                      "total_cost_usd": 0.25, "duration_ms": 1200, "num_turns": 4})
USAGE_LIMIT = json.dumps({"type": "result", "subtype": "success", "is_error": True,
                          "api_error_status": 429, "terminal_reason": "api_error",
                          "result": "Session limit reached"})


def assistant(message_id, *tools):
    content = [{"type": "text", "text": "thinking"}]
    content += [{"type": "tool_use", "name": name, "input": {}} for name in tools]
    return {"type": "assistant", "message": {"id": message_id, "content": content}}


def fake_claude(tmp_path, monkeypatch, body):
    script = tmp_path / "fake_claude"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(run_eval, "CLAUDE", str(script))


def test_mcp_config_uses_absolute_paths():
    log = ROOT / "logs" / "RUN" / "depth_8_seed3.jsonl"
    server = run_eval.mcp_config("depth_8_seed3", 8, 45, 3, log)["mcpServers"]["cube"]
    assert server["command"] == str(ROOT / ".venv" / "bin" / "python")
    assert server["args"] == [str(ROOT / "mcp_server.py")]
    assert Path(server["command"]).is_absolute() and Path(server["args"][0]).is_absolute()
    assert server["env"] == {"CUBE_SCRAMBLE_SEED": "3", "CUBE_SCRAMBLE_DEPTH": "8",
                             "CUBE_MOVE_BUDGET": "45", "CUBE_LOG_PATH": str(log),
                             "CUBE_GAME_ID": "depth_8_seed3"}
    random = run_eval.mcp_config("g", "random", 100, 0, log)["mcpServers"]["cube"]
    assert random["env"]["CUBE_SCRAMBLE_DEPTH"] == "random"


def test_claude_command(tmp_path):
    config = tmp_path / "game.mcp.json"
    cmd = run_eval.claude_command(config, 5.0)

    def value(flag):
        return cmd[cmd.index(flag) + 1]

    assert cmd[:3] == [run_eval.CLAUDE, "-p", "Solve the cube. Start by calling get_state."]
    assert value("--output-format") == "stream-json" and "--verbose" in cmd
    assert value("--mcp-config") == str(config) and "--strict-mcp-config" in cmd
    assert value("--tools") == ""
    assert value("--allowedTools") == "mcp__cube__get_state,mcp__cube__make_move"
    assert value("--permission-prompts") == "none"
    assert value("--append-system-prompt") == run_eval.SOLVER_PROMPT
    assert value("--max-budget-usd") == "5"
    assert {"--no-session-persistence", "--disable-slash-commands"} <= set(cmd)
    for absent in ("--model", "--effort", "--max-turns", "--bare", "--safe-mode",
                   "--dangerously-skip-permissions"):
        assert absent not in cmd
    # Variadic options must be followed by another option, not the prompt.
    for flag in ("--mcp-config", "--tools", "--allowedTools"):
        assert cmd[cmd.index(flag) + 2].startswith("--")

    cmd = run_eval.claude_command(config, 0.005, model="sonnet", effort="high")
    assert cmd[cmd.index("--model") + 1] == "sonnet"
    assert cmd[cmd.index("--effort") + 1] == "high"
    assert cmd[cmd.index("--max-budget-usd") + 1] == "0.005"


def test_user_prompt_never_contains_the_board():
    assert "U (Up)" not in run_eval.USER_PROMPT and "W W W" not in run_eval.USER_PROMPT


def test_solver_prompt_is_design_md_section_4_verbatim():
    doc = (ROOT / "docs" / "DESIGN.md").read_text()
    section = doc.split("## 4. Solver system prompt", 1)[1].split("\n## ", 1)[0]
    assert run_eval.SOLVER_PROMPT == section.split("```\n", 1)[1].split("\n```", 1)[0]


def test_child_env_strips_nested_session_markers(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", "/tmp/x.sock")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    monkeypatch.setenv("CUBE_TEST_KEEP", "yes")
    env = run_eval.child_env()
    assert not {"CLAUDECODE", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_ENTRYPOINT"} & set(env)
    assert env["CUBE_TEST_KEEP"] == "yes" and "PATH" in env


@pytest.mark.parametrize("result, returncode, timed_out, expected", [
    ({"subtype": "success", "is_error": False}, 0, False, None),
    # A clean finish whose final text happens to mention a limit is still clean.
    ({"subtype": "success", "is_error": False, "result": "no rate limit hit"}, 0, False, None),
    (None, None, True, "timeout"),
    (None, 1, False, "claude_error"),
    # Observed when --max-budget-usd trips (claude 2.1.269, cap $0.001):
    ({"type": "result", "subtype": "error_max_budget_usd", "is_error": True,
      "terminal_reason": "budget_exhausted", "stop_reason": "tool_use", "num_turns": 1,
      "errors": ["Reached maximum budget ($0.001)"], "total_cost_usd": 0.0460425},
     1, False, "max_budget_usd"),
    ({"subtype": "error_during_execution", "is_error": True}, 1, False, "claude_error"),
    ({"subtype": "success", "is_error": False}, 1, False, "claude_error"),
    # Observed when the account's usage limit is hit:
    ({"subtype": "success", "is_error": True, "terminal_reason": "api_error",
      "api_error_status": 429, "result": "You've hit your session limit · resets 11:20pm"},
     1, False, "usage_limit"),
    ({"subtype": "success", "is_error": True, "result": "Usage limit reached"}, 1, False,
     "usage_limit"),
])
def test_cutoff_reason(result, returncode, timed_out, expected):
    assert run_eval.cutoff_reason(result, returncode, timed_out) == expected


def test_parallel_move_batches():
    events = [
        {"type": "system", "subtype": "init"},
        assistant("a", STATE),
        assistant("b", MOVE),
        assistant("c", MOVE, MOVE, MOVE),     # a batch
        assistant("d", MOVE), assistant("d", MOVE),  # one message streamed as two events
        assistant("e", MOVE, STATE),          # one move plus a state read: not a batch
        {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
        {"type": "result", "subtype": "success"},
    ]
    assert run_eval.parallel_move_batches(events) == 2
    assert run_eval.parallel_move_batches([]) == 0


def test_model_used():
    # As observed: a small Haiku side call is listed before the model that played.
    result = {"type": "result", "modelUsage": {"claude-haiku-4-5-20251001": {"costUSD": 0.001},
                                               "claude-opus-5": {"costUSD": 0.079}}}
    assert run_eval.model_used([json.loads(INIT), result]) == "claude-test"
    assert run_eval.model_used([result]) == "claude-opus-5"
    assert run_eval.model_used([]) is None


def played(tmp_path, moves, budget=3):
    """Log of a real Game (depth 3, seed 1) after the given moves."""
    game = Game(seed=1, depth=3, budget=budget, log_path=tmp_path / "g.jsonl", game_id="g")
    start = json.loads(game.log_path.read_text().splitlines()[0])
    solution = [m[:-1] if m.endswith("'") else m if m.endswith("2") else m + "'"
                for m in reversed(start["scramble_moves"])]
    game.get_state()
    for move in (solution if moves == "solve" else moves):
        game.make_move(move)
    return game.log_path


def test_game_metrics_from_server_logs(tmp_path):
    assert run_eval.game_metrics(played(tmp_path / "a", "solve")) == {
        "outcome": "solved", "solved": True, "moves_used": 3, "invalid_move_count": 0,
        "solved_sticker_fraction": 1.0}
    exhausted = run_eval.game_metrics(played(tmp_path / "b", ["I", "y", "y", "y"]))
    assert exhausted["outcome"] == "exhausted" and exhausted["moves_used"] == 3
    assert exhausted["invalid_move_count"] == 1 and exhausted["solved"] is False
    abandoned = run_eval.game_metrics(played(tmp_path / "c", ["y"]))
    assert abandoned["outcome"] == "abandoned" and abandoned["moves_used"] == 1
    assert 0 < abandoned["solved_sticker_fraction"] < 1
    assert run_eval.game_metrics(tmp_path / "missing.jsonl") == {
        "outcome": "abandoned", "solved": False, "moves_used": 0, "invalid_move_count": 0,
        "solved_sticker_fraction": None}


def test_rung_summary_and_table():
    games = [
        {"game_id": "depth_1_seed0", "outcome": "solved", "moves_used": 2,
         "invalid_move_count": 1, "solved_sticker_fraction": 1.0, "cutoff_reason": None},
        {"game_id": "depth_1_seed1", "outcome": "solved", "moves_used": 4,
         "invalid_move_count": 0, "solved_sticker_fraction": 1.0, "cutoff_reason": None},
        {"game_id": "depth_1_seed2", "outcome": "abandoned", "moves_used": 7,
         "invalid_move_count": 2, "solved_sticker_fraction": 0.5, "cutoff_reason": "timeout"},
    ]
    rung = run_eval.rung_summary("depth_1", games)
    assert rung["outcomes"] == {"solved": 2, "exhausted": 0, "abandoned": 1}
    assert (rung["scramble_depth"], rung["move_budget"], rung["games"]) == (1, 10, 3)
    assert rung["solved_rate"] == 0.6667
    assert rung["avg_moves_used_when_solved"] == 3
    assert rung["avg_invalid_move_count"] == 1
    assert rung["avg_solved_sticker_fraction"] == 0.8333
    assert rung["per_game"] == games
    table = run_eval.format_table([rung]).splitlines()
    assert table[0].split() == ["difficulty", "games", "solved", "solved_rate",
                                "avg_moves(solved)", "avg_invalid", "avg_sticker_frac"]
    assert table[1].split() == ["depth_1", "3", "2", "0.67", "3.0", "1.0", "0.83"]
    assert table[-1].strip() == "depth_1_seed2: timeout"


def test_run_game_with_fake_claude(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    probe = tmp_path / "probe"
    batch = json.dumps(assistant("m1", MOVE, MOVE))
    fake_claude(tmp_path, monkeypatch, f"""
pwd > {probe}.cwd
ls -A | wc -l > {probe}.files
env > {probe}.env
echo '{INIT}'
echo '{batch}'
echo '{SUCCESS}'
""")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    record = run_eval.run_game(run_dir, "depth_1", 0, OPTS)
    assert record == {"game_id": "depth_1_seed0", "seed": 0, "outcome": "abandoned",
                      "solved": False, "moves_used": 0, "invalid_move_count": 0,
                      "solved_sticker_fraction": None, "parallel_move_batches": 1,
                      "model": "claude-test", "cost_usd": 0.25, "duration_ms": 1200,
                      "num_turns": 4, "cutoff_reason": None}
    cwd = Path(probe.with_suffix(".cwd").read_text().strip())
    assert int(probe.with_suffix(".files").read_text()) == 0  # fresh and empty
    assert not cwd.exists()  # and removed afterwards
    assert "CLAUDECODE=" not in probe.with_suffix(".env").read_text()
    saved = json.loads((run_dir / "depth_1_seed0.claude.json").read_text())
    assert saved["result"]["total_cost_usd"] == 0.25 and saved["returncode"] == 0
    assert (run_dir / "depth_1_seed0.stream.jsonl").read_text().splitlines()[0] == INIT
    config = json.loads((run_dir / "depth_1_seed0.mcp.json").read_text())
    assert config["mcpServers"]["cube"]["env"]["CUBE_LOG_PATH"] \
        == str((run_dir / "depth_1_seed0.jsonl").resolve())


def test_run_game_timeout_kills_claude(tmp_path, monkeypatch):
    fake_claude(tmp_path, monkeypatch, "sleep 60\n")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    record = run_eval.run_game(run_dir, "depth_2", 3, argparse.Namespace(
        **{**vars(OPTS), "timeout": 1}))
    assert record["cutoff_reason"] == "timeout"
    assert record["cost_usd"] is None and record["outcome"] == "abandoned"


def test_run_game_unparseable_output(tmp_path, monkeypatch):
    fake_claude(tmp_path, monkeypatch, "echo 'something went wrong' >&2\nexit 1\n")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    record = run_eval.run_game(run_dir, "depth_1", 0, OPTS)
    assert record["cutoff_reason"] == "claude_error" and record["model"] is None
    saved = json.loads((run_dir / "depth_1_seed0.claude.json").read_text())
    assert saved["returncode"] == 1 and "something went wrong" in saved["stderr"]


def test_usage_limit_stops_the_sweep_and_resume_finishes_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run_eval, "LOGS", tmp_path / "logs")
    calls = tmp_path / "calls"
    fake_claude(tmp_path, monkeypatch, f"""
echo x >> {calls}
if [ "$(wc -l < {calls})" -eq 2 ]; then
  echo '{USAGE_LIMIT}'
else
  echo '{INIT}'
  echo '{SUCCESS}'
fi
""")
    summary = run_eval.main(["--rungs", "depth_1", "depth_2", "--seeds", "0", "1"])
    run_dir = tmp_path / "logs" / summary["run_id"]
    assert len(calls.read_text().split()) == 2  # stopped right after the limited game
    assert [g["game_id"] for r in summary["ladder"] for g in r["per_game"]] == ["depth_1_seed0"]
    assert summary["ladder"][0]["games"] == 1  # the limited game doesn't count
    assert summary["not_run"] == [{"game_id": "depth_1_seed1", "reason": "usage_limit"},
                                  {"game_id": "depth_2_seed0", "reason": "not_started"},
                                  {"game_id": "depth_2_seed1", "reason": "not_started"}]
    assert json.loads((run_dir / "summary.json").read_text()) == summary
    out = capsys.readouterr().out
    assert "usage limit reached" in out and f"--resume {summary['run_id']}" in out

    stale = run_dir / "depth_1_seed1.jsonl"  # the server logs its start before the 429
    Game(seed=1, depth=1, budget=10, log_path=stale, game_id="depth_1_seed1")
    resumed = run_eval.main(["--resume", summary["run_id"]])
    assert len(calls.read_text().split()) == 5  # only the three unfinished games ran
    assert resumed["not_run"] == []
    assert [r["games"] for r in resumed["ladder"]] == [2, 2]
    assert resumed["config"]["models_used"] == ["claude-test"]
    assert resumed["config"]["seeds"] == [0, 1] and resumed["config"]["model"] is None
    assert not stale.exists()  # the rerun started a fresh server log
