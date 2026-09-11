"""Cross-validation of cube.py against pycuber; skipped if it isn't installed."""

import random

import pytest

from cube import FACES, MOVES, Cube

pc = pytest.importorskip("pycuber")

FACE_TOKENS = sorted(m for m in MOVES if m[0] in "UDRLFB" and "w" not in m)


def pycuber_facelets(alg):
    """Apply alg with pycuber and read the state back in Kociemba order.

    pycuber has its own color scheme, so each sticker is mapped back to the
    face whose center had that color when solved. Its get_face() grids use
    the same row/column orientation as the Kociemba layout.
    """
    cube = pc.Cube()
    home = {cube.get_face(f)[1][1].colour: f for f in FACES}
    cube(pc.Formula(alg))
    return "".join(home[cube.get_face(f)[r][c].colour]
                   for f in FACES for r in range(3) for c in range(3))


def ours(alg):
    cube = Cube()
    cube.apply(alg)
    return cube.facelets()


@pytest.mark.parametrize("move", sorted(MOVES))
def test_single_move_matches_pycuber(move):
    assert ours(move) == pycuber_facelets(move)


@pytest.mark.parametrize("tokens", [FACE_TOKENS, sorted(MOVES)], ids=["face", "all"])
def test_random_sequences_match_pycuber(tokens):
    rng = random.Random(2026)
    for _ in range(250):
        alg = " ".join(rng.choice(tokens) for _ in range(rng.randint(1, 25)))
        assert ours(alg) == pycuber_facelets(alg), alg
