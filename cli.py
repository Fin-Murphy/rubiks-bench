"""Human REPL over the cube engine (DESIGN.md §5): no move budget, no hidden
scramble, no logging. Run: .venv/bin/python cli.py"""

from cube import (VALID_TOKENS_HELP, Cube, parse_move, render_state,
                  uniform_count)

HELP = """\
Commands:
  scramble     uniform random-state scramble
  scramble N   random N-move scramble (no consecutive same-face moves)
  reset        return to solved
  show         reprint the current state
  <move>       apply one move, e.g. R, U2, Rw', x
  help         show this help
  quit, exit   leave

Moves:
  Face turns:  U D R L F B            (clockwise, looking straight at that face)
  Wide turns:  Uw Dw Rw Lw Fw Bw  or lowercase  u d r l f b   (turns the outer 2 layers)
  Rotations:   x y z                  (x follows R, y follows U, z follows F - turns the whole cube)
  Slices:      M E S                  (M follows L, E follows D, S follows F - turns the middle layer)
  Modifiers:   append ' for counterclockwise, 2 (or 2') for a 180 degree turn.
  Examples: R, U', F2, Rw, r2, M', y, x2"""


def state_text(cube: Cube) -> str:
    facelets = cube.facelets()
    status = "SOLVED" if cube.is_solved() else "IN_PROGRESS"
    return (f"{render_state(facelets)}\n\n"
            f"Uniform stickers: {uniform_count(facelets)}/54\nStatus: {status}")


def run_command(cube: Cube, line: str) -> str | None:
    """Execute one REPL line. Returns the text to print, or None to quit."""
    words = line.split()
    if not words:
        return ""
    if words in (["quit"], ["exit"]):
        return None
    if words == ["help"]:
        return HELP
    if words == ["show"]:
        return state_text(cube)
    if words == ["reset"]:
        cube.reset()
        return state_text(cube)
    if words[0] == "scramble":
        if len(words) == 1:
            cube.scramble()
        elif len(words) == 2 and words[1].isdigit():
            cube.scramble(int(words[1]))
        else:
            return "Usage: scramble [N]"
        return state_text(cube)
    try:
        move = parse_move(line)
    except ValueError:
        return (f'Invalid move: "{line.strip()}" is not a recognized move token. '
                f"No changes made.\n\n{VALID_TOKENS_HELP}")
    cube.apply(move)
    return f"Applied: {move}\n\n{state_text(cube)}"


def main():
    cube = Cube()
    print(state_text(cube))
    print("\nType help for commands.\n")
    while True:
        try:
            line = input("> ")
        except EOFError:
            print()
            break
        output = run_command(cube, line)
        if output is None:
            break
        if output:
            print(output, end="\n\n")


if __name__ == "__main__":
    main()
