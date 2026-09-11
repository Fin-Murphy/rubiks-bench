"""The MCP tool layer (DESIGN.md §2): in-process, and over real stdio."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

import mcp_server  # noqa: E402
from game import Game  # noqa: E402
from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def new_server(tmp_path):
    game = Game(seed=1, depth=3, budget=10, log_path=tmp_path / "game.jsonl", game_id="t")
    return game, mcp_server.build_server(game)


def call(server, name, arguments):
    result = asyncio.run(server.call_tool(name, arguments))
    assert not result.is_error
    [content] = result.content
    return content.text


def test_exactly_two_tools_as_specified(tmp_path):
    _, server = new_server(tmp_path)
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert set(tools) == {"get_state", "make_move"}
    assert tools["get_state"].description == (
        "Return the current cube state as text, without making any move. "
        "Free — does not use any of the move budget.")
    assert tools["get_state"].input_schema["properties"] == {}
    assert tools["make_move"].description == (
        "Apply exactly one cube move in standard notation and return the resulting state. "
        "Invalid tokens are rejected and do not change the cube or use any of the move budget.")
    schema = tools["make_move"].input_schema
    assert schema["required"] == ["move"]
    assert schema["properties"]["move"]["type"] == "string"
    assert schema["properties"]["move"]["description"] == (
        'One move token, e.g. "R", "U\'", "F2", "Rw", "r2", "M\'", "y", "x2".')


def test_tools_call_the_game(tmp_path):
    game, server = new_server(tmp_path)
    assert call(server, "get_state", {}) == game.get_state()
    assert call(server, "make_move", {"move": "R"}).startswith("Applied: R\n")
    assert call(server, "make_move", {"move": "I"}).startswith('Invalid move: "I"')
    assert (game.moves_used, game.invalid_move_count) == (1, 1)


def test_game_from_env(tmp_path):
    log = tmp_path / "logs" / "depth_8_seed3.jsonl"
    mcp_server.game_from_env({"CUBE_SCRAMBLE_SEED": "3", "CUBE_SCRAMBLE_DEPTH": "8",
                              "CUBE_MOVE_BUDGET": "45", "CUBE_LOG_PATH": str(log),
                              "CUBE_GAME_ID": "depth_8_seed3"})
    start = json.loads(log.read_text().splitlines()[0])
    assert (start["game_id"], start["scramble_seed"], start["scramble_depth"],
            start["move_budget"], len(start["scramble_moves"])) == ("depth_8_seed3", 3, 8, 45, 8)


def test_game_from_env_defaults_to_random_state(tmp_path):
    log = tmp_path / "game.jsonl"
    mcp_server.game_from_env({"CUBE_SCRAMBLE_SEED": "0", "CUBE_MOVE_BUDGET": "100",
                              "CUBE_LOG_PATH": str(log)})
    start = json.loads(log.read_text().splitlines()[0])
    assert start["scramble_depth"] == "random" and start["scramble_moves"] is None
    assert start["game_id"].startswith("game_")


def test_round_trip_over_stdio(tmp_path):
    """The real server process, spoken to over stdio the way claude does."""
    log = tmp_path / "game.jsonl"
    params = StdioServerParameters(
        command=sys.executable, args=[str(ROOT / "mcp_server.py")], cwd=str(tmp_path),
        env={"CUBE_SCRAMBLE_SEED": "2", "CUBE_SCRAMBLE_DEPTH": "4",
             "CUBE_MOVE_BUDGET": "10", "CUBE_LOG_PATH": str(log), "CUBE_GAME_ID": "stdio"})

    async def session():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = await client.list_tools()
                state = await client.call_tool("get_state", {})
                moved = await client.call_tool("make_move", {"move": "R"})
                return tools, state, moved

    tools, state, moved = asyncio.run(asyncio.wait_for(session(), 60))
    assert sorted(t.name for t in tools.tools) == ["get_state", "make_move"]
    assert "\nStatus: IN_PROGRESS — in progress" in state.content[0].text
    assert moved.content[0].text.startswith("Applied: R\n")
    log_events = [json.loads(line) for line in log.read_text().splitlines()]
    assert [(e["event"], e.get("tool")) for e in log_events] == [
        ("start", None), ("call", "get_state"), ("call", "make_move")]
