"""Smoke tests for the human REPL (DESIGN.md §5), run as a real subprocess."""

import subprocess
import sys
from pathlib import Path

import cli
from cube import SOLVED, VALID_TOKENS_HELP, Cube, render_state

ROOT = Path(__file__).resolve().parent.parent


def run_cli(stdin):
    return subprocess.run([sys.executable, str(ROOT / "cli.py")], input=stdin,
                          capture_output=True, text=True, timeout=30, cwd=ROOT)


def test_session():
    r = run_cli("R\nRw3\nshow\nscramble 5\nscramble x\nscramble\nreset\nhelp\nquit\nU\n")
    assert r.returncode == 0 and r.stderr == ""
    out = r.stdout
    assert out.startswith(f"{render_state(SOLVED)}\n\nUniform stickers: 54/54\nStatus: SOLVED\n")
    after_r = Cube()
    after_r.apply("R")
    applied = f"Applied: R\n\n{render_state(after_r.facelets())}\n\nUniform stickers: 42/54\n" \
              "Status: IN_PROGRESS"
    assert applied in out
    assert ('Invalid move: "Rw3" is not a recognized move token. No changes made.\n\n'
            + VALID_TOKENS_HELP) in out
    assert out.count("U (Up)") == 6  # start, R, show, scramble 5, scramble, reset
    assert "Usage: scramble [N]" in out
    assert "Commands:" in out
    assert "Applied: U" not in out  # nothing runs after quit


def test_exits_cleanly_at_end_of_input():
    r = run_cli("R\n")
    assert r.returncode == 0 and r.stderr == ""
    assert "Applied: R" in r.stdout


def test_help_uses_the_solver_prompts_notation_wording():
    prompt = (ROOT / "prompts" / "solver_system.txt").read_text()
    notation = cli.HELP.split("Moves:\n", 1)[1].splitlines()
    assert len(notation) == 6
    assert all(line in prompt.splitlines() for line in notation)
