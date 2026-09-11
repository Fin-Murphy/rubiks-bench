"""One budgeted solve attempt: game rules, tool result text and the JSONL log
(DESIGN.md §2, §3, §6). Plain Python; mcp_server.py exposes it as MCP tools."""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from cube import (VALID_TOKENS_HELP, Cube, compact_state, parse_move,
                  render_state, uniform_count)

_STATUS = {  # result -> (status word, message)
    None: ("IN_PROGRESS", "in progress"),
    "solved": ("SOLVED", "cube solved in {moves} moves. Stop calling tools and report success."),
    "exhausted": ("OUT_OF_MOVES", "move budget exhausted before solving. "
                                  "Stop calling tools and report the result."),
}


class Game:
    """A scrambled cube with a move budget. Every tool call is logged."""

    def __init__(self, seed: int, depth: int | str, budget: int, log_path, game_id: str):
        """depth: number of scramble moves, or "random" for a random-state scramble."""
        self.budget = budget
        self.log_path = Path(log_path)
        self.moves_used = 0
        self.invalid_move_count = 0
        self.result = None  # "solved" or "exhausted" once the game is over
        self.cube = Cube()
        self._turn = 0
        self._lock = threading.Lock()  # the MCP SDK runs sync tools in worker threads
        scramble = self.cube.scramble(None if depth == "random" else depth, rng=seed)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log("start", game_id=game_id, scramble_depth=depth, scramble_seed=seed,
                  move_budget=budget, scramble_moves=scramble,
                  initial_state=self._compact())

    def get_state(self) -> str:
        with self._lock:
            self._log_call("get_state", {}, "ok")
            return self._state_text()

    def make_move(self, move: str) -> str:
        with self._lock:
            if self.result:
                self._log_call("make_move", {"move": move}, "already_over")
                return (f"Game already over ({self._status()[0]} after {self.moves_used} "
                        "moves). No further moves accepted.")
            try:
                token = parse_move(move)
            except ValueError:
                self.invalid_move_count += 1
                self._log_call("make_move", {"move": move}, "invalid",
                               error="not a recognized move token")
                return (f'Invalid move: "{move}" is not a recognized move token. '
                        f"No changes made.\n\n{VALID_TOKENS_HELP}\n\n{self._state_text()}")
            self.cube.apply(token)
            self.moves_used += 1
            if self.cube.is_solved():  # checked first: solving on the last move counts
                self.result = "solved"
            elif self.moves_used >= self.budget:
                self.result = "exhausted"
            self._log_call("make_move", {"move": move}, self.result or "ok")
            if self.result:
                self._log("end", result=self.result, moves_used=self.moves_used,
                          invalid_move_count=self.invalid_move_count,
                          solved_sticker_fraction=round(
                              uniform_count(self.cube.facelets()) / 54, 4),
                          final_state=self._compact())
            return f"Applied: {token}\n\n{self._state_text()}"

    def _status(self):
        word, message = _STATUS[self.result]
        return word, message.format(moves=self.moves_used)

    def _state_text(self):
        facelets = self.cube.facelets()
        word, message = self._status()
        return (f"{render_state(facelets)}\n\n"
                f"Moves used: {self.moves_used}/{self.budget}\n"
                f"Uniform stickers: {uniform_count(facelets)}/54\n"
                f"Status: {word} — {message}")

    def _compact(self):
        return compact_state(self.cube.facelets())

    def _log_call(self, tool, arguments, outcome, **extra):
        self._log("call", turn=self._turn, tool=tool, input=arguments, outcome=outcome,
                  **extra, moves_used=self.moves_used, state_after=self._compact())
        self._turn += 1

    def _log(self, event, **fields):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.log_path.open("a") as f:
            f.write(json.dumps({"event": event, "ts": ts, **fields}) + "\n")
