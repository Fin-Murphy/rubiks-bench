"""Game rules, tool result text and the JSONL log (DESIGN.md §2, §3, §6)."""

import json
import re
import threading

import pytest

from cube import (SOLVED, VALID_TOKENS_HELP, Cube, compact_state, render_state,
                  uniform_count)
from game import Game

TS = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


def new_game(tmp_path, depth=3, budget=10, seed=1):
    return Game(seed=seed, depth=depth, budget=budget,
                log_path=tmp_path / "game.jsonl", game_id="test_game")


def events(game):
    return [json.loads(line) for line in game.log_path.read_text().splitlines()]


def scramble_of(game):
    return events(game)[0]["scramble_moves"]


def inverse(moves):
    return [m[:-1] if m.endswith("'") else m if m.endswith("2") else m + "'"
            for m in reversed(moves)]


def test_start_event(tmp_path):
    game = new_game(tmp_path, depth=5, seed=4)
    [start] = events(game)
    assert list(start) == ["event", "ts", "game_id", "scramble_depth", "scramble_seed",
                           "move_budget", "scramble_moves", "initial_state"]
    assert TS.fullmatch(start["ts"])
    assert (start["game_id"], start["scramble_depth"], start["scramble_seed"],
            start["move_budget"]) == ("test_game", 5, 4, 10)
    assert len(start["scramble_moves"]) == 5
    replay = Cube()
    replay.apply(" ".join(start["scramble_moves"]))
    assert start["initial_state"] == compact_state(replay.facelets()) \
        == compact_state(game.cube.facelets())


def test_random_state_game_logs_no_scramble_moves(tmp_path):
    game = new_game(tmp_path, depth="random", seed=4)
    [start] = events(game)
    assert start["scramble_depth"] == "random"
    assert start["scramble_moves"] is None
    assert start["initial_state"] == compact_state(game.cube.facelets())
    assert not game.cube.is_solved()


def test_same_seed_same_scramble(tmp_path):
    a = new_game(tmp_path / "a", depth=8, seed=5)
    b = new_game(tmp_path / "b", depth=8, seed=5)
    assert a.cube.facelets() == b.cube.facelets()


@pytest.mark.parametrize("seed", range(5))
def test_shorter_rungs_scramble_a_prefix_of_longer_ones(tmp_path, seed):
    scrambles = [scramble_of(new_game(tmp_path / str(d), depth=d, seed=seed))
                 for d in (1, 2, 3, 5, 8, 12)]
    assert all(longer[:len(shorter)] == shorter
               for shorter, longer in zip(scrambles, scrambles[1:]))


def test_get_state_is_free(tmp_path):
    game = new_game(tmp_path)
    text = game.get_state()
    facelets = game.cube.facelets()
    assert text == (f"{render_state(facelets)}\n\n"
                    "Moves used: 0/10\n"
                    f"Uniform stickers: {uniform_count(facelets)}/54\n"
                    "Status: IN_PROGRESS — in progress")
    assert game.get_state() == text
    assert game.moves_used == 0


def test_valid_move_uses_one_move_of_budget(tmp_path):
    game = new_game(tmp_path)
    expected = Cube()
    expected.apply(" ".join(scramble_of(game)) + " R")
    text = game.make_move("R")
    assert game.moves_used == 1
    assert game.cube.facelets() == expected.facelets()
    assert text == "Applied: R\n\n" + game.get_state()
    assert "\nMoves used: 1/10\n" in text


def test_move_token_is_normalized(tmp_path):
    game = new_game(tmp_path)
    assert game.make_move(" r’ ").startswith("Applied: r'\n")


@pytest.mark.parametrize("bad", ["Rw3", "I", "R U", "", " ", "rw", "R3", "hello"])
def test_invalid_move_is_free_and_changes_nothing(tmp_path, bad):
    game = new_game(tmp_path)
    game.make_move("y")
    before = game.cube.facelets()
    text = game.make_move(bad)
    assert text == (f'Invalid move: "{bad}" is not a recognized move token. No changes made.'
                    f"\n\n{VALID_TOKENS_HELP}\n\n{game.get_state()}")
    assert game.cube.facelets() == before
    assert (game.moves_used, game.invalid_move_count, game.result) == (1, 1, None)


def test_solving_move_reports_solved(tmp_path):
    game = new_game(tmp_path, depth=3)
    *first, last = inverse(scramble_of(game))
    for move in first:
        assert game.make_move(move).endswith("Status: IN_PROGRESS — in progress")
    assert game.make_move(last).endswith(
        "Moves used: 3/10\nUniform stickers: 54/54\n"
        "Status: SOLVED — cube solved in 3 moves. Stop calling tools and report success.")
    assert game.result == "solved"


def test_running_out_of_moves(tmp_path):
    game = new_game(tmp_path, budget=2)
    game.make_move("y")  # a rotation never solves a scrambled cube
    text = game.make_move("y")
    assert "\nMoves used: 2/2\n" in text
    assert text.endswith("Status: OUT_OF_MOVES — move budget exhausted before solving. "
                         "Stop calling tools and report the result.")
    assert game.result == "exhausted"


def test_solved_takes_precedence_over_out_of_moves(tmp_path):
    game = new_game(tmp_path, depth=3, budget=3)
    for move in inverse(scramble_of(game)):
        text = game.make_move(move)
    assert "Status: SOLVED" in text and "OUT_OF_MOVES" not in text
    assert events(game)[-1]["result"] == "solved"


@pytest.mark.parametrize("ending, word", [("solved", "SOLVED"), ("exhausted", "OUT_OF_MOVES")])
def test_game_over_rejects_moves_but_get_state_still_works(tmp_path, ending, word):
    game = new_game(tmp_path, depth=3, budget=3)
    for move in inverse(scramble_of(game)) if ending == "solved" else ["y", "y", "y"]:
        game.make_move(move)
    final = game.cube.facelets()
    for move in ("R", "Rw3"):
        assert game.make_move(move) == (f"Game already over ({word} after 3 moves). "
                                        "No further moves accepted.")
    assert game.cube.facelets() == final
    assert (game.moves_used, game.invalid_move_count) == (3, 0)
    state = game.get_state()
    assert state.startswith(render_state(final))
    assert "\nMoves used: 3/3\n" in state and f"\nStatus: {word} — " in state


def test_log_events(tmp_path):
    game = new_game(tmp_path, depth=3)
    solution = inverse(scramble_of(game))
    game.get_state()
    game.make_move("Rw3")
    game.make_move("y")
    game.make_move("y'")
    for move in solution:
        game.make_move(move)
    game.make_move("R")
    game.get_state()

    log = events(game)
    assert [e["event"] for e in log] == ["start"] + ["call"] * 7 + ["end"] + ["call"] * 2
    assert all(TS.fullmatch(e["ts"]) for e in log)
    calls = [e for e in log if e["event"] == "call"]
    assert [c["turn"] for c in calls] == list(range(9))
    assert [c["tool"] for c in calls] == ["get_state"] + ["make_move"] * 7 + ["get_state"]
    assert [c["input"] for c in calls] == (
        [{}, {"move": "Rw3"}, {"move": "y"}, {"move": "y'"}]
        + [{"move": m} for m in solution] + [{"move": "R"}, {}])
    assert [c["outcome"] for c in calls] == ["ok", "invalid", "ok", "ok", "ok", "ok",
                                             "solved", "already_over", "ok"]
    assert [c["moves_used"] for c in calls] == [0, 0, 1, 2, 3, 4, 5, 5, 5]
    assert calls[1]["error"] == "not a recognized move token"
    for c in calls:
        assert list(c) == (["event", "ts", "turn", "tool", "input", "outcome"]
                           + (["error"] if c["outcome"] == "invalid" else [])
                           + ["moves_used", "state_after"])
    assert calls[0]["state_after"] == log[0]["initial_state"]
    assert calls[-1]["state_after"] == compact_state(SOLVED)
    end = log[8]
    assert end == {"event": "end", "ts": end["ts"], "result": "solved", "moves_used": 5,
                   "invalid_move_count": 1, "solved_sticker_fraction": 1.0,
                   "final_state": compact_state(SOLVED)}


def test_scramble_never_appears_in_tool_results(tmp_path):
    game = new_game(tmp_path, depth=12, budget=30, seed=7)
    scramble = scramble_of(game)
    texts = [game.get_state(), game.make_move("R"), game.make_move("R'"),
             game.make_move("nonsense"), game.make_move("R U")]
    texts += [game.make_move(move) for move in inverse(scramble)]
    texts += [game.make_move("U"), game.get_state()]
    assert game.result == "solved"
    leaks = [" ".join(scramble), ",".join(scramble), "".join(scramble),
             json.dumps(scramble), str(scramble)]
    assert not [(leak, text) for text in texts for leak in leaks if leak in text]


def test_concurrent_calls_are_serialized(tmp_path):
    game = new_game(tmp_path, budget=1000)
    threads = ([threading.Thread(target=game.make_move, args=("y",)) for _ in range(40)]
               + [threading.Thread(target=game.get_state) for _ in range(10)])
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    calls = [e for e in events(game) if e["event"] == "call"]
    assert game.moves_used == 40
    assert sorted(c["turn"] for c in calls) == list(range(50))
    assert sorted(c["moves_used"] for c in calls if c["tool"] == "make_move") \
        == list(range(1, 41))
