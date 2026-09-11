"""3x3 Rubik's cube engine: facelet state, move notation and scrambles.

Stdlib only. The state is 54 face letters in Kociemba order U1-U9, R1-R9,
F1-F9, D1-D9, L1-L9, B1-B9. Each face is read row by row: U seen from above
with B at the top, D seen from below with F at the top, and L, F, R, B seen
from outside with U at the top. A letter names the face a sticker belongs to
when solved; COLORS maps letters to display colors.
"""

import random

FACES = "URFDLB"
SOLVED = "".join(face * 9 for face in FACES)
COLORS = {"U": "W", "R": "R", "F": "G", "D": "Y", "L": "O", "B": "B"}

# ---------------------------------------------------------------------------
# Geometry. +x points to R, +y to U, +z to F. Per face: the outward normal,
# then the "right" and "down" directions of its reading order.
_FRAMES = {
    "U": ((0, 1, 0), (1, 0, 0), (0, 0, 1)),
    "R": ((1, 0, 0), (0, 0, -1), (0, -1, 0)),
    "F": ((0, 0, 1), (1, 0, 0), (0, -1, 0)),
    "D": ((0, -1, 0), (1, 0, 0), (0, 0, -1)),
    "L": ((-1, 0, 0), (0, 0, 1), (0, -1, 0)),
    "B": ((0, 0, -1), (-1, 0, 0), (0, -1, 0)),
}

# Every facelet as (position of its cubie, normal), in facelet order.
_STICKERS = [
    (tuple(n + (col - 1) * r + (row - 1) * d for n, r, d in zip(*_FRAMES[face])),
     _FRAMES[face][0])
    for face in FACES for row in range(3) for col in range(3)
]
_STICKER_INDEX = {sticker: i for i, sticker in enumerate(_STICKERS)}


def _dot(u, v):
    return sum(a * b for a, b in zip(u, v))


def _quarter_turn(face, layers):
    """Permutation turning `layers` a quarter turn clockwise as seen facing `face`.

    Layers are counted along the face's normal: 1 is the face itself, 0 the
    middle slice, -1 the opposite face. A permutation p takes state s to
    [s[i] for i in p].
    """
    a = _FRAMES[face][0]

    def rotate(v):  # clockwise about a: (a.v)a + v x a
        k = _dot(a, v)
        return (k * a[0] + v[1] * a[2] - v[2] * a[1],
                k * a[1] + v[2] * a[0] - v[0] * a[2],
                k * a[2] + v[0] * a[1] - v[1] * a[0])

    perm = list(range(54))
    for i, (pos, normal) in enumerate(_STICKERS):
        if _dot(a, pos) in layers:
            perm[_STICKER_INDEX[rotate(pos), rotate(normal)]] = i
    return perm


def _compose(*perms):
    """The permutation that applies `perms` in order."""
    result = list(range(54))
    for p in perms:
        result = [result[i] for i in p]
    return result


def _with_modifiers(names, p):
    p2 = _compose(p, p)
    p3 = _compose(p2, p)
    return {name + mod: q for name in names
            for mod, q in (("", p), ("'", p3), ("2", p2), ("2'", p2))}


def _build_moves():
    quarter = {face: _quarter_turn(face, {1}) for face in FACES}
    quarter["M"] = _quarter_turn("L", {0})         # M follows L
    quarter["E"] = _quarter_turn("D", {0})         # E follows D
    quarter["S"] = _quarter_turn("F", {0})         # S follows F
    quarter["x"] = _quarter_turn("R", {-1, 0, 1})  # x follows R
    quarter["y"] = _quarter_turn("U", {-1, 0, 1})  # y follows U
    quarter["z"] = _quarter_turn("F", {-1, 0, 1})  # z follows F
    moves = {}
    for name, p in quarter.items():
        moves.update(_with_modifiers([name], p))
    # Wide moves: the face plus the adjacent slice turned the same way.
    for face, slice_move in (("U", "E'"), ("D", "E"), ("R", "M'"),
                             ("L", "M"), ("F", "S"), ("B", "S'")):
        wide = _compose(moves[face], moves[slice_move])
        moves.update(_with_modifiers([face + "w", face.lower()], wide))
    return moves


# Every accepted move (with ASCII prime) -> permutation.
MOVES = _build_moves()


def parse(alg: str) -> list[str]:
    """Split a move sequence on whitespace into validated moves.

    Raises ValueError naming the first invalid token. The unicode prime (’) is
    accepted and normalized to an apostrophe.
    """
    moves = []
    for token in alg.split():
        move = token.replace("’", "'")
        if move not in MOVES:
            raise ValueError(
                f"invalid move {token!r}: expected U D R L F B, Uw..Bw or "
                "u d r l f b, M E S, or x y z, optionally followed by ' 2 or 2'")
        moves.append(move)
    return moves


def parse_move(text: str) -> str:
    """Validate text as exactly one move token (surrounding whitespace allowed)."""
    moves = parse(text)
    if len(moves) != 1:
        raise ValueError(f"expected exactly one move, got {text!r}")
    return moves[0]


# ---------------------------------------------------------------------------
# Presentation, shared by the CLI and the MCP server (DESIGN.md §1).
VALID_TOKENS_HELP = (
    "Valid tokens: face turns U D R L F B; wide Uw Dw Rw Lw Fw Bw (or lowercase u d r l f b);\n"
    "slices M E S; rotations x y z — each optionally followed by ' (counterclockwise) or 2\n"
    "(180 degrees, 2' also accepted).")


def compact_state(facelets: str) -> str:
    """The 54 stickers as color letters in URFDLB order, for logs."""
    return "".join(COLORS[f] for f in facelets)


def uniform_count(state: str) -> int:
    """Stickers matching their face's majority color; 54 when solved in any
    orientation. Works on facelet and compact color strings alike."""
    faces = [state[i:i + 9] for i in range(0, 54, 9)]
    return sum(max(face.count(c) for c in face) for face in faces)


def render_state(facelets: str) -> str:
    """Unfolded net: U above F, then L F R B side by side, then D below F.

    Face headers plus 3x3 grids of color letters. L/F/R/B start at columns
    2/14/26/38, U and D at column 14. No footer, no trailing whitespace.
    """
    colors = compact_state(facelets)

    def row(face, r):
        start = FACES.index(face) * 9 + r * 3
        return " ".join(colors[start:start + 3])

    def band(cells):
        return ("  " + "".join(cell.ljust(12) for cell in cells)).rstrip()

    pad = " " * 14
    lines = [pad + "U (Up)"] + [pad + row("U", r) for r in range(3)]
    lines += ["", band(["L (Left)", "F (Front)", "R (Right)", "B (Back)"])]
    lines += [band([row(face, r) for face in "LFRB"]) for r in range(3)]
    lines += ["", pad + "D (Down)"] + [pad + row("D", r) for r in range(3)]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cubie model (Kociemba tables). Corners URF UFL ULB UBR DFR DLF DBL DRB, each
# listed clockwise from its U/D facelet; edges UR UF UL UB DR DF DL DB FR FL
# BL BR. cp[i]/ep[i] is the piece sitting in position i, co[i]/eo[i] its
# twist/flip.
def _facelet(name):
    return FACES.index(name[0]) * 9 + int(name[1]) - 1


_CORNER_FACELETS = [[_facelet(n) for n in corner.split()] for corner in (
    "U9 R1 F3", "U7 F1 L3", "U1 L1 B3", "U3 B1 R3",
    "D3 F9 R7", "D1 L9 F7", "D7 B9 L7", "D9 R9 B7")]
_EDGE_FACELETS = [[_facelet(n) for n in edge.split()] for edge in (
    "U6 R2", "U8 F2", "U4 L2", "U2 B2", "D6 R8", "D2 F8",
    "D4 L8", "D8 B8", "F6 R4", "F4 L6", "B6 L4", "B4 R6")]
_CORNER_COLORS = ["".join(SOLVED[i] for i in c) for c in _CORNER_FACELETS]
_EDGE_COLORS = ["".join(SOLVED[i] for i in e) for e in _EDGE_FACELETS]


def cubies_to_facelets(cp, co, ep, eo) -> str:
    """Facelet string of a cubie state (centers in standard position)."""
    f = list(SOLVED)
    for i, (piece, ori) in enumerate(zip(cp, co)):
        for k in range(3):
            f[_CORNER_FACELETS[i][(k + ori) % 3]] = _CORNER_COLORS[piece][k]
    for i, (piece, ori) in enumerate(zip(ep, eo)):
        for k in range(2):
            f[_EDGE_FACELETS[i][(k + ori) % 2]] = _EDGE_COLORS[piece][k]
    return "".join(f)


def facelets_to_cubies(facelets: str):
    """Inverse of cubies_to_facelets: returns (cp, co, ep, eo).

    Requires centers in standard position; raises ValueError for stickers
    that don't form real pieces.
    """
    if facelets[4::9] != FACES:
        raise ValueError("centers are not in standard URFDLB position")
    cp, co, ep, eo = [], [], [], []
    for positions in _CORNER_FACELETS:
        colors = "".join(facelets[i] for i in positions)
        for ori in range(3):
            if colors[ori] in "UD":
                break
        cp.append(_CORNER_COLORS.index(colors[ori:] + colors[:ori]))
        co.append(ori)
    for positions in _EDGE_FACELETS:
        colors = "".join(facelets[i] for i in positions)
        if colors in _EDGE_COLORS:
            ep.append(_EDGE_COLORS.index(colors))
            eo.append(0)
        else:
            ep.append(_EDGE_COLORS.index(colors[::-1]))
            eo.append(1)
    return cp, co, ep, eo


def _parity(perm):
    """0 for an even permutation, 1 for odd."""
    return sum(a > b for i, a in enumerate(perm) for b in perm[i + 1:]) % 2


def _random_cubies(rng):
    """Uniformly random legal cubie state."""
    cp = list(range(8))
    ep = list(range(12))
    rng.shuffle(cp)
    rng.shuffle(ep)
    if _parity(cp) != _parity(ep):
        ep[0], ep[1] = ep[1], ep[0]  # a bijection odd <-> even, so still uniform
    co = [rng.randrange(3) for _ in range(7)]
    co.append(-sum(co) % 3)
    eo = [rng.randrange(2) for _ in range(11)]
    eo.append(sum(eo) % 2)
    return cp, co, ep, eo


_AXIS = {"U": 0, "D": 0, "R": 1, "L": 1, "F": 2, "B": 2}


def _random_moves(n, rng):
    """n random face turns: never the same face twice in a row, never three
    in a row on one axis (so no R L R)."""
    if n < 0:
        raise ValueError("scramble length must be non-negative")
    # Each modifier is drawn right after its face, so for a given seed the
    # shorter scrambles are prefixes of the longer ones.
    moves = []
    while len(moves) < n:
        face = rng.choice(FACES)
        if moves and face == moves[-1][0]:
            continue
        if len(moves) >= 2 and _AXIS[face] == _AXIS[moves[-1][0]] == _AXIS[moves[-2][0]]:
            continue
        moves.append(face + rng.choice(("", "'", "2")))
    return moves


class Cube:
    """A 3x3 cube. Starts solved."""

    def __init__(self):
        self._state = list(SOLVED)

    def apply(self, alg: str) -> None:
        """Apply a move sequence. Invalid input raises ValueError and changes nothing."""
        for move in parse(alg):
            perm = MOVES[move]
            self._state = [self._state[i] for i in perm]

    def is_solved(self) -> bool:
        """True if every face is one color, whatever the cube's orientation."""
        s = self._state
        return all(len(set(s[i:i + 9])) == 1 for i in range(0, 54, 9))

    def reset(self) -> None:
        self._state = list(SOLVED)

    def scramble(self, n: int | None = None, rng=None) -> list[str] | None:
        """Replace the state with a random legal one.

        n=None: uniform random state over all legal states; returns None.
        n=int: reset, then apply n random face turns; returns the moves.
        rng: a random.Random, a seed, or None for fresh OS entropy.
        """
        if not isinstance(rng, random.Random):
            rng = random.Random(rng)
        if n is None:
            self._state = list(cubies_to_facelets(*_random_cubies(rng)))
            return None
        moves = _random_moves(n, rng)
        self.reset()
        self.apply(" ".join(moves))
        return moves

    def copy(self) -> "Cube":
        other = Cube()
        other._state = list(self._state)
        return other

    def facelets(self) -> str:
        """The 54-letter state in URFDLB order."""
        return "".join(self._state)

    def render(self) -> str:
        """The unfolded net of the current state (see render_state)."""
        return render_state(self.facelets())
