"""Golden tests for the text rendering shared by the CLI and the MCP server
(DESIGN.md §1)."""

from cube import FACES, SOLVED, Cube, compact_state, render_state, uniform_count

SOLVED_NET = """\
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
              Y Y Y"""

AFTER_R_NET = """\
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
              Y Y B"""


def after(alg):
    cube = Cube()
    cube.apply(alg)
    return cube.facelets()


def test_solved_net():
    assert render_state(SOLVED) == SOLVED_NET
    assert Cube().render() == SOLVED_NET


def test_net_after_r():
    assert render_state(after("R")) == AFTER_R_NET


def test_compact_state():
    assert compact_state(SOLVED) == "WWWWWWWWWRRRRRRRRRGGGGGGGGGYYYYYYYYYOOOOOOOOOBBBBBBBBB"
    assert compact_state(after("R")) == "WWGWWGWWGRRRRRRRRRGGYGGYGGYYYBYYBYYBOOOOOOOOOWBBWBBWBB"


def test_net_alignment():
    cube = Cube()
    cube.scramble(rng=9)
    colors = compact_state(cube.facelets())
    lines = render_state(cube.facelets()).split("\n")

    def grid(face, r):
        start = FACES.index(face) * 9 + r * 3
        return " ".join(colors[start:start + 3])

    assert len(lines) == 14
    assert all(line == line.rstrip() for line in lines)
    assert lines[0] == " " * 14 + "U (Up)"
    assert lines[1:4] == [" " * 14 + grid("U", r) for r in range(3)]
    assert lines[4] == lines[9] == ""
    assert lines[5] == "  L (Left)    F (Front)   R (Right)   B (Back)"
    assert [lines[5].index(h) for h in ("L (Left)", "F (Front)", "R (Right)", "B (Back)")] \
        == [2, 14, 26, 38]
    for r in range(3):
        line = lines[6 + r]
        assert [line[col:col + 5] for col in (2, 14, 26, 38)] == [grid(f, r) for f in "LFRB"]
        assert line == "  " + "       ".join(grid(f, r) for f in "LFRB")
    assert lines[10] == " " * 14 + "D (Down)"
    assert lines[11:14] == [" " * 14 + grid("D", r) for r in range(3)]


def test_uniform_count():
    assert uniform_count(SOLVED) == 54
    assert uniform_count(after("R")) == uniform_count(compact_state(after("R"))) == 42
    assert uniform_count(after("M")) == 42
    assert uniform_count(after("y")) == uniform_count(after("x z'")) == 54
