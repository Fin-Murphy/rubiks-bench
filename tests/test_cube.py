"""Tests for cube.py. Run from the project root: .venv/bin/python -m pytest"""

import random
import re

import pytest

from cube import (FACES, MOVES, SOLVED, Cube, cubies_to_facelets,
                  facelets_to_cubies, parse, parse_move)

IDENTITY = tuple(range(54))
BASE_MOVES = (list("UDRLFB") + [f + "w" for f in "UDRLFB"] + list("udrlfb")
              + list("MESxyz"))
FACE_MOVES = [f + m for f in "UDRLFB" for m in ("", "'", "2")]


def idx(name):
    """Facelet index of a name like 'U9'."""
    return FACES.index(name[0]) * 9 + int(name[1]) - 1


def perm(alg):
    """Apply alg to a cube whose 54 stickers are all distinct (labelled 0-53)."""
    state = IDENTITY
    for move in parse(alg):
        state = tuple(state[i] for i in MOVES[move])
    return state


def order(alg):
    p = perm(alg)
    state, k = p, 1
    while state != IDENTITY:
        state = tuple(state[i] for i in p)
        k += 1
    return k


def after(alg):
    cube = Cube()
    cube.apply(alg)
    return cube.facelets()


def cycle_parity(p):
    """Permutation parity by cycle counting (cube.py uses inversions)."""
    seen, parity = set(), 0
    for start in range(len(p)):
        length, j = 0, start
        while j not in seen:
            seen.add(j)
            j = p[j]
            length += 1
        parity ^= max(length - 1, 0) % 2
    return parity


def assert_legal(facelets):
    assert all(facelets.count(f) == 9 for f in FACES)
    cp, co, ep, eo = facelets_to_cubies(facelets)
    assert sorted(cp) == list(range(8))
    assert sorted(ep) == list(range(12))
    assert cycle_parity(cp) == cycle_parity(ep), "corner/edge parity mismatch"
    assert sum(co) % 3 == 0, "corner twist"
    assert sum(eo) % 2 == 0, "edge flip"
    assert cubies_to_facelets(cp, co, ep, eo) == facelets


# --- Basics ----------------------------------------------------------------

def test_starts_solved():
    cube = Cube()
    assert cube.facelets() == SOLVED == "U" * 9 + "R" * 9 + "F" * 9 + "D" * 9 + "L" * 9 + "B" * 9
    assert cube.is_solved()


def test_move_table_is_exactly_the_notation():
    assert set(MOVES) == {b + m for b in BASE_MOVES for m in ("", "'", "2", "2'")}


def test_reset():
    cube = Cube()
    cube.apply("R U F' x M")
    cube.reset()
    assert cube.facelets() == SOLVED


def test_copy_is_independent():
    cube = Cube()
    cube.apply("R")
    clone = cube.copy()
    clone.apply("U")
    assert cube.facelets() == after("R")
    assert clone.facelets() == after("R U")


def test_apply_matches_permutation_composition():
    rng = random.Random(1)
    for _ in range(50):
        alg = " ".join(rng.choice(list(MOVES)) for _ in range(20))
        assert after(alg) == "".join(SOLVED[i] for i in perm(alg))


# --- Group identities ------------------------------------------------------

@pytest.mark.parametrize("move", sorted(MOVES))
def test_every_move_four_times_is_identity(move):
    assert perm(" ".join([move] * 4)) == IDENTITY


@pytest.mark.parametrize("move", BASE_MOVES)
def test_prime_is_inverse(move):
    assert perm(f"{move} {move}'") == IDENTITY
    assert perm(f"{move}' {move}") == IDENTITY


@pytest.mark.parametrize("move", BASE_MOVES)
def test_double_is_two_quarters(move):
    assert perm(f"{move}2") == perm(f"{move} {move}") == perm(f"{move}2'")


@pytest.mark.parametrize("move", BASE_MOVES)
def test_quarter_turn_is_not_identity(move):
    assert perm(move) != IDENTITY
    assert perm(f"{move}2") != IDENTITY


@pytest.mark.parametrize("alg, equivalent", [
    ("Rw", "R M'"), ("Lw", "L M"), ("Uw", "U E'"),
    ("Dw", "D E"), ("Fw", "F S"), ("Bw", "B S'"),
    ("r", "Rw"), ("l", "Lw"), ("u", "Uw"), ("d", "Dw"), ("f", "Fw"), ("b", "Bw"),
    ("x", "R M' L'"), ("y", "U E' D'"), ("z", "F S B'"),
])
def test_equivalent_algs(alg, equivalent):
    assert perm(alg) == perm(equivalent)


@pytest.mark.parametrize("alg, expected", [
    ("R U", 105), ("R U R' U'", 6), ("R U2 D' B D'", 1260),
])
def test_move_orders(alg, expected):
    assert order(alg) == expected


# --- Hand-checked moves ----------------------------------------------------

# Facelets after one move from solved, face by face in URFDLB order. Checked
# against the jperm.net pictures (Rubik's Cube Move Notation.pdf), which use
# yellow top / blue front: U=yellow F=blue R=red D=white L=orange B=green.
AFTER_ONE_MOVE = {
    #      U            R            F            D            L            B
    "U": ("UUUUUUUUU", "BBBRRRRRR", "RRRFFFFFF", "DDDDDDDDD", "FFFLLLLLL", "LLLBBBBBB"),
    "D": ("UUUUUUUUU", "RRRRRRFFF", "FFFFFFLLL", "DDDDDDDDD", "LLLLLLBBB", "BBBBBBRRR"),
    "R": ("UUFUUFUUF", "RRRRRRRRR", "FFDFFDFFD", "DDBDDBDDB", "LLLLLLLLL", "UBBUBBUBB"),
    "L": ("BUUBUUBUU", "RRRRRRRRR", "UFFUFFUFF", "FDDFDDFDD", "LLLLLLLLL", "BBDBBDBBD"),
    "F": ("UUUUUULLL", "URRURRURR", "FFFFFFFFF", "RRRDDDDDD", "LLDLLDLLD", "BBBBBBBBB"),
    "B": ("RRRUUUUUU", "RRDRRDRRD", "FFFFFFFFF", "DDDDDDLLL", "ULLULLULL", "BBBBBBBBB"),
    "M": ("UBUUBUUBU", "RRRRRRRRR", "FUFFUFFUF", "DFDDFDDFD", "LLLLLLLLL", "BDBBDBBDB"),
    "E": ("UUUUUUUUU", "RRRFFFRRR", "FFFLLLFFF", "DDDDDDDDD", "LLLBBBLLL", "BBBRRRBBB"),
    "S": ("UUULLLUUU", "RURRURRUR", "FFFFFFFFF", "DDDRRRDDD", "LDLLDLLDL", "BBBBBBBBB"),
    "x": ("FFFFFFFFF", "RRRRRRRRR", "DDDDDDDDD", "BBBBBBBBB", "LLLLLLLLL", "UUUUUUUUU"),
    "y": ("UUUUUUUUU", "BBBBBBBBB", "RRRRRRRRR", "DDDDDDDDD", "FFFFFFFFF", "LLLLLLLLL"),
    "z": ("LLLLLLLLL", "UUUUUUUUU", "FFFFFFFFF", "RRRRRRRRR", "DDDDDDDDD", "BBBBBBBBB"),
    "Uw": ("UUUUUUUUU", "BBBBBBRRR", "RRRRRRFFF", "DDDDDDDDD", "FFFFFFLLL", "LLLLLLBBB"),
    "Dw": ("UUUUUUUUU", "RRRFFFFFF", "FFFLLLLLL", "DDDDDDDDD", "LLLBBBBBB", "BBBRRRRRR"),
    "Rw": ("UFFUFFUFF", "RRRRRRRRR", "FDDFDDFDD", "DBBDBBDBB", "LLLLLLLLL", "UUBUUBUUB"),
    "Lw": ("BBUBBUBBU", "RRRRRRRRR", "UUFUUFUUF", "FFDFFDFFD", "LLLLLLLLL", "BDDBDDBDD"),
    "Fw": ("UUULLLLLL", "UURUURUUR", "FFFFFFFFF", "RRRRRRDDD", "LDDLDDLDD", "BBBBBBBBB"),
    "Bw": ("RRRRRRUUU", "RDDRDDRDD", "FFFFFFFFF", "DDDLLLLLL", "UULUULUUL", "BBBBBBBBB"),
}


@pytest.mark.parametrize("move", AFTER_ONE_MOVE)
def test_single_move_from_solved(move):
    assert after(move) == "".join(AFTER_ONE_MOVE[move])


# Exact sticker cycles of each face turn: "A B C D" means the sticker at A
# moves to B, B's to C, C's to D and D's to A. Pins down the order within
# each strip, which the solved-cube pictures above can't show.
FACE_TURN_CYCLES = {
    "U": ["U1 U3 U9 U7", "U2 U6 U8 U4", "F1 L1 B1 R1", "F2 L2 B2 R2", "F3 L3 B3 R3"],
    "D": ["D1 D3 D9 D7", "D2 D6 D8 D4", "F7 R7 B7 L7", "F8 R8 B8 L8", "F9 R9 B9 L9"],
    "R": ["R1 R3 R9 R7", "R2 R6 R8 R4", "F3 U3 B7 D3", "F6 U6 B4 D6", "F9 U9 B1 D9"],
    "L": ["L1 L3 L9 L7", "L2 L6 L8 L4", "U1 F1 D1 B9", "U4 F4 D4 B6", "U7 F7 D7 B3"],
    "F": ["F1 F3 F9 F7", "F2 F6 F8 F4", "U7 R1 D3 L9", "U8 R4 D2 L6", "U9 R7 D1 L3"],
    "B": ["B1 B3 B9 B7", "B2 B6 B8 B4", "U1 L7 D9 R3", "U2 L4 D8 R6", "U3 L1 D7 R9"],
}


@pytest.mark.parametrize("move", FACE_TURN_CYCLES)
def test_face_turn_sticker_cycles(move):
    expected = list(IDENTITY)
    for cycle in FACE_TURN_CYCLES[move]:
        names = cycle.split()
        for src, dst in zip(names, names[1:] + names[:1]):
            expected[idx(dst)] = idx(src)
    assert perm(move) == tuple(expected)


# Kociemba's cubie-level definitions of the face turns (cubie.py in his
# two-phase solver): the piece in each position after the move, plus its
# twist/flip. Pins the facelet tables to his orientation convention.
URF, UFL, ULB, UBR, DFR, DLF, DBL, DRB = range(8)
UR, UF, UL, UB, DR, DF, DL, DB, FR, FL, BL, BR = range(12)
KOCIEMBA_FACE_TURNS = {
    "U": ([UBR, URF, UFL, ULB, DFR, DLF, DBL, DRB], [0] * 8,
          [UB, UR, UF, UL, DR, DF, DL, DB, FR, FL, BL, BR], [0] * 12),
    "R": ([DFR, UFL, ULB, URF, DRB, DLF, DBL, UBR], [2, 0, 0, 1, 1, 0, 0, 2],
          [FR, UF, UL, UB, BR, DF, DL, DB, DR, FL, BL, UR], [0] * 12),
    "F": ([UFL, DLF, ULB, UBR, URF, DFR, DBL, DRB], [1, 2, 0, 0, 2, 1, 0, 0],
          [UR, FL, UL, UB, DR, FR, DL, DB, UF, DF, BL, BR],
          [0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 0]),
    "D": ([URF, UFL, ULB, UBR, DLF, DBL, DRB, DFR], [0] * 8,
          [UR, UF, UL, UB, DF, DL, DB, DR, FR, FL, BL, BR], [0] * 12),
    "L": ([URF, ULB, DBL, UBR, DFR, UFL, DLF, DRB], [0, 1, 2, 0, 0, 2, 1, 0],
          [UR, UF, BL, UB, DR, DF, FL, DB, FR, UL, DL, BR], [0] * 12),
    "B": ([URF, UFL, UBR, DRB, DFR, DLF, ULB, DBL], [0, 0, 1, 2, 0, 0, 2, 1],
          [UR, UF, UL, BR, DR, DF, DL, BL, FR, FL, UB, DB],
          [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1]),
}


@pytest.mark.parametrize("move", KOCIEMBA_FACE_TURNS)
def test_face_turns_match_kociemba_cubie_definitions(move):
    cubies = KOCIEMBA_FACE_TURNS[move]
    assert facelets_to_cubies(after(move)) == cubies
    assert cubies_to_facelets(*cubies) == after(move)


@pytest.mark.parametrize("alg, expected", [
    # From docs/RESEARCH.md §3 (Kociemba engine + pycuber + kociemba.solve).
    ("R U R' U'", "UULUUFUUFRRUBRRURRFFDFFUFFFDDRDDDDDDBLLLLLLLLBRRBBBBBB"),
    ("M2 E2 S2", "UDUDUDUDURLRLRLRLRFBFBFBFBFDUDUDUDUDLRLRLRLRLBFBFBFBFB"),
    # Superflip (Reid's 20-move alg): every edge flipped in place.
    ("U R2 F B R B2 R U2 L B2 R U' D' R2 F R' L B2 U2 F2",
     "UBULURUFURURFRBRDRFUFLFRFDFDFDLDRDBDLULBLFLDLBUBRBLBDB"),
    # Checkerboard.
    ("U2 D2 F2 B2 L2 R2",
     "UDUDUDUDU" "RLRLRLRLR" "FBFBFBFBF" "DUDUDUDUD" "LRLRLRLRL" "BFBFBFBFB"),
])
def test_known_patterns(alg, expected):
    assert after(alg) == expected


# --- Solved check ----------------------------------------------------------

@pytest.mark.parametrize("alg", ["x", "y2", "z'", "x y z", "r L'", "u D'", "f B'"])
def test_is_solved_ignores_orientation(alg):
    cube = Cube()
    cube.apply(alg)
    assert cube.is_solved()
    assert cube.facelets() != SOLVED


@pytest.mark.parametrize("alg", ["R", "M", "E2", "S'", "r", "R U R' U'"])
def test_is_solved_false_when_scrambled(alg):
    cube = Cube()
    cube.apply(alg)
    assert not cube.is_solved()


def test_sexy_move_six_times_solves():
    cube = Cube()
    cube.apply("R U R' U' " * 5)
    assert not cube.is_solved()
    cube.apply("R U R' U'")
    assert cube.facelets() == SOLVED


# --- Parser ----------------------------------------------------------------

def test_parse_accepts_all_notation():
    alg = ("U D R L F B U' R2 F2' Uw Dw' Rw2 Lw2' Fw Bw' u d' r2 l2' f b' "
           "M M' M2 E' S2' x y' z2 x2'")
    assert parse(alg) == alg.split()


def test_parse_normalizes_unicode_prime():
    assert parse("R’ U2’ x’ r’") == ["R'", "U2'", "x'", "r'"]


def test_parse_whitespace():
    assert parse("  R\tU\n F  ") == ["R", "U", "F"]
    assert parse("") == []


@pytest.mark.parametrize("token", [
    "I", "R3", "Q", "X", "Y", "rw", "R'2", "RU", "R,", "2", "'", "Mw", "m",
    "Rw'2", "R''", "(R", "R2''", "U'’", "i", "uw", "R1", "R0",
])
def test_parse_rejects_invalid_tokens(token):
    with pytest.raises(ValueError, match=re.escape(repr(token))):
        parse(f"R {token} U")


def test_invalid_move_leaves_state_unchanged():
    cube = Cube()
    cube.apply("R U F")
    before = cube.facelets()
    with pytest.raises(ValueError, match="'I'"):
        cube.apply("L D I B")
    assert cube.facelets() == before


def test_parse_move_accepts_exactly_one_token():
    assert parse_move("R") == "R"
    assert parse_move("  r’ \n") == "r'"
    for bad in ("", "  ", "R U", "I", "R3"):
        with pytest.raises(ValueError):
            parse_move(bad)


# --- Scrambles and legality ------------------------------------------------

def test_face_move_states_are_legal():
    rng = random.Random(11)
    for _ in range(200):
        assert_legal(after(" ".join(rng.choice(FACE_MOVES) for _ in range(30))))


def _rotations():
    """The 24 whole-cube orientations, as permutations."""
    found, frontier = {IDENTITY}, [IDENTITY]
    while frontier:
        p = frontier.pop()
        for g in (MOVES["x"], MOVES["y"]):
            q = tuple(p[i] for i in g)
            if q not in found:
                found.add(q)
                frontier.append(q)
    return found


def test_any_move_sequence_is_legal_after_reorienting():
    rotations = _rotations()
    assert len(rotations) == 24
    rng = random.Random(12)
    for _ in range(200):
        f = after(" ".join(rng.choice(list(MOVES)) for _ in range(30)))
        oriented = [g for g in ("".join(f[i] for i in r) for r in rotations)
                    if g[4::9] == FACES]
        assert len(oriented) == 1
        assert_legal(oriented[0])


def test_random_state_scrambles_are_legal():
    rng = random.Random(2024)
    seen = set()
    for _ in range(500):
        cube = Cube()
        assert cube.scramble(rng=rng) is None
        f = cube.facelets()
        assert f[4::9] == FACES
        assert_legal(f)
        seen.add(f)
    assert len(seen) == 500


def test_random_state_covers_parities_twists_and_flips():
    rng = random.Random(7)
    parity, twists, flips = set(), set(), set()
    for _ in range(300):
        cube = Cube()
        cube.scramble(rng=rng)
        cp, co, ep, eo = facelets_to_cubies(cube.facelets())
        parity.add(cycle_parity(cp))
        twists.add((co[0], co[7]))
        flips.add((eo[0], eo[11]))
    assert parity == {0, 1}
    assert {a for a, _ in twists} == {b for _, b in twists} == {0, 1, 2}
    assert {a for a, _ in flips} == {b for _, b in flips} == {0, 1}


def test_scramble_replaces_existing_state():
    cube = Cube()
    cube.apply("R U")
    cube.scramble(rng=3)
    fresh = Cube()
    fresh.scramble(rng=3)
    assert cube.facelets() == fresh.facelets()


def test_scramble_is_reproducible():
    a, b = Cube(), Cube()
    a.scramble(rng=42)
    b.scramble(rng=random.Random(42))
    assert a.facelets() == b.facelets()
    assert a.scramble(25, rng=5) == b.scramble(25, rng=5)
    assert a.facelets() == b.facelets()


@pytest.mark.parametrize("n", [0, 1, 2, 3, 25, 200])
def test_move_scramble(n):
    cube = Cube()
    cube.apply("R U")  # scramble(n) starts from solved
    moves = cube.scramble(n, rng=random.Random(n))
    assert len(moves) == n
    assert all(m[0] in "UDRLFB" and m[1:] in ("", "'", "2") for m in moves)
    faces = [m[0] for m in moves]
    axis = {"U": 0, "D": 0, "R": 1, "L": 1, "F": 2, "B": 2}
    assert all(a != b for a, b in zip(faces, faces[1:]))
    assert not any(axis[a] == axis[b] == axis[c]
                   for a, b, c in zip(faces, faces[1:], faces[2:]))
    assert cube.facelets() == after(" ".join(moves))


def test_move_scramble_rejects_negative_length():
    with pytest.raises(ValueError):
        Cube().scramble(-1)
