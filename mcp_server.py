"""MCP stdio server "cube" with the LLM-facing tools get_state and make_move
(DESIGN.md §2). The game is scrambled once, at startup, from env vars:

  CUBE_SCRAMBLE_SEED   int, required
  CUBE_SCRAMBLE_DEPTH  int, or "random" for a random-state scramble (default)
  CUBE_MOVE_BUDGET     int, required
  CUBE_LOG_PATH        JSONL log path (default: logs/<timestamp>.jsonl here)
  CUBE_GAME_ID         id for the log's start event (default: game_<timestamp>)
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from game import Game

GET_STATE_DESCRIPTION = ("Return the current cube state as text, without making any move. "
                         "Free — does not use any of the move budget.")
MAKE_MOVE_DESCRIPTION = ("Apply exactly one cube move in standard notation and return the "
                         "resulting state. Invalid tokens are rejected and do not change the "
                         "cube or use any of the move budget.")
MOVE_DESCRIPTION = 'One move token, e.g. "R", "U\'", "F2", "Rw", "r2", "M\'", "y", "x2".'


def game_from_env(env=os.environ) -> Game:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    depth = env.get("CUBE_SCRAMBLE_DEPTH", "random")
    default_log = Path(__file__).resolve().parent / "logs" / f"{stamp}.jsonl"
    return Game(seed=int(env["CUBE_SCRAMBLE_SEED"]),
                depth=depth if depth == "random" else int(depth),
                budget=int(env["CUBE_MOVE_BUDGET"]),
                log_path=env.get("CUBE_LOG_PATH") or default_log,
                game_id=env.get("CUBE_GAME_ID") or f"game_{stamp}")


def build_server(game: Game) -> MCPServer:
    server = MCPServer("cube")

    @server.tool(description=GET_STATE_DESCRIPTION, structured_output=False)
    def get_state() -> str:
        return game.get_state()

    @server.tool(description=MAKE_MOVE_DESCRIPTION, structured_output=False)
    def make_move(move: Annotated[str, Field(description=MOVE_DESCRIPTION)]) -> str:
        return game.make_move(move)

    return server


if __name__ == "__main__":
    build_server(game_from_env()).run("stdio")
