# Research — Rubik's Cube LLM Solver

Compiled by `researcher`. All facelet strings and move-order claims in §3 were independently computed two ways (a hand-built engine using Kociemba's own permutation tables, and the `pycuber` library) and cross-checked against the `kociemba` solver — see §1 and §3 for method.

---

## 1. Reference library for cross-validation

**Recommendation: `pycuber` (pip install `pycuber`, v0.2.2), used alongside `kociemba` (pip install `kociemba`) as a second, independent check.**

### Why `pycuber`
It's the only common option that both **applies arbitrary move strings** (not just solves) and **supports the project's full notation set**. Verified directly:

```python
import pycuber as pc
c = pc.Cube()
c(pc.Formula("Rw2 M E' S x y' z2 U2'"))   # wide, slice, rotation, and 2' all parse and apply
```
Confirmed working: face turns, wide moves in both spellings (`Rw` and `r`), slices `M E S`, rotations `x y z`, and modifiers `'`, `2`, `2'` (`U2'` produces the identical state to `U2`, as expected since a 180° turn has no direction).

### API usage
```python
import pycuber as pc
c = pc.Cube()                      # solved cube
c(pc.Formula("R U R' U'"))         # apply a sequence in place
grid = c.get_face('U')             # 3x3 list-of-lists of Square objects
colour = grid[0][0].colour         # e.g. 'yellow' (full colour name, not a letter)
```
There's no built-in "export as Kociemba string" method — you read `get_face()` for all six faces and translate colours to face letters yourself (see below).

### Quirks
- **Own colour scheme**, not WCA: solved cube is U=yellow, D=white, F=green, B=blue, L=red, R=orange (WCA is U=white, D=yellow, L=orange, R=red — L/R and U/D are swapped relative to WCA). This doesn't matter for cross-validation: build a `colour → home-face-letter` map from the solved cube once (`yellow→U, white→D, green→F, blue→B, red→L, orange→R`), then translate any scrambled cube's colours through that map. The map is colour-scheme-independent because it tracks *origin face*, which is exactly what a Kociemba facelet string encodes.
- **Own facelet layout when printed** — but empirically it is the *same* net orientation as the Kociemba convention (verified below in §2), so `get_face(X)`'s row 0/row 2 and col 0/col 2 map directly onto Kociemba's `X1..X9` without any extra transposition, once translated through the colour map and re-ordered into `U,R,F,D,L,B` face order.
- Package is unmaintained (last PyPI release years old) but works fine on current Python; only exposes classes `Cube`, `Formula`, `Square` — no facelet-index API, so the row/col translation must be written once in test helpers.

### Why also keep `kociemba`
`kociemba` (muodov/kociemba port of Herbert Kociemba's two-phase algorithm) does **not** apply moves or export state — its only function is `kociemba.solve(cubestring, pattern=None) -> "move sequence"`. But that makes it an excellent independent *validator*: feed it any facelet string your engine produces and confirm (a) it doesn't raise (facelet string is well-formed and has legal corner/edge parity, twist, and flip), and (b) the returned solution is sane — e.g. solving the string for a single `R` move should return exactly `R'`. This is a strictly stronger check than "does it look right" and it's basically free once your engine emits Kociemba-order strings. Install: `pip install kociemba`.

### Verified example (what this actually catches)
```
kociemba.solve(<facelet string after R>)        -> "R'"          (1 move)
kociemba.solve(<facelet string after R U R' U'>) -> "U R U' R'"   (4 moves, exact group inverse)
```
Both check out exactly (see §3) — strong confirmation the facelet convention and move logic are right, not just "some string that looks plausible."

Other options considered and rejected for this role: `magiccube`/`RubikTwoPhase` (NxNxN-focused, thinner move-notation support, less battle-tested); `rubik-cube` (pglass) (educational, narrower notation, no wide/slice support found); raw `hkociemba/RubiksCube-TwophaseSolver` (this *is* the ground truth we're validating against — using it as the "independent" library would be circular, though its own source files are the best citation for the facelet convention itself, see §2).

---

## 2. Exact facelet convention

Source of truth: [`hkociemba/RubiksCube-TwophaseSolver`](https://github.com/hkociemba/RubiksCube-TwophaseSolver) — `enums.py` (index definitions) and `defs.py` (`cornerFacelet`, `edgeFacelet`, `cornerColor`, `edgeColor` tables). This is Herbert Kociemba's own reference implementation, so it's authoritative for "the Kociemba convention." Confirmed against [muodov/kociemba's README](https://github.com/muodov/kociemba) (same diagram, same solved string) and empirically re-derived via `pycuber` face-turn tests (below).

### Index layout (0-based; `U1`..`B9` = 0..53)
```
                |************|
                |*U1**U2**U3*|
                |************|
                |*U4**U5**U6*|
                |************|
                |*U7**U8**U9*|
                |************|
 ***************|************|************|************|
 *L1**L2**L3*   |*F1**F2**F3*|*R1**R2**R3*|*B1**B2**B3*|
 ***************|************|************|************|
 *L4**L5**L6*   |*F4**F5**F6*|*R4**R5**R6*|*B4**B5**B6*|
 ***************|************|************|************|
 *L7**L8**L9*   |*F7**F8**F9*|*R7**R8**R9*|*B7**B8**B9*|
 ***************|************|************|************|
                |************|
                |*D1**D2**D3*|
                |************|
                |*D4**D5**D6*|
                |************|
                |*D7**D8**D9*|
                |************|
```
Facelet string order: `U1,U2,...,U9, R1,...,R9, F1,...,F9, D1,...,D9, L1,...,L9, B1,...,B9` (indices 0–53). Solved cube: `UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB`. A character at position i is the *original home face* of the sticker currently there, not its physical colour — e.g. `kociemba.solve('DRLUU...')` means position `U1` currently holds a sticker whose home face is D, etc.

This matches the project brief's stated orientation exactly:
- **U** read with **B at top** — `U1,U2,U3` (row 0) is the edge adjacent to B; `U7,U8,U9` (row 2) is adjacent to F.
- **D** read with **F at top** — `D1,D2,D3` adjacent to F; `D7,D8,D9` adjacent to B.
- **L,F,R,B** each read with **U at top** — row 0 (`X1,X2,X3`) adjacent to U, row 2 (`X7,X8,X9`) adjacent to D.
- Columns: `F`'s col 0 (`F1,F4,F7`) adjacent to L, col 2 adjacent to R. `R`'s col 0 adjacent to F, col 2 adjacent to B. `B`'s col 0 adjacent to R, col 2 adjacent to L (B "wraps around" the net, so its L-adjacent column prints on the right). `L`'s col 0 adjacent to B, col 2 adjacent to F.

I independently re-confirmed every one of these row/column adjacency claims empirically: applied single reference moves (`F`, `R`, `U`, `L`) with `pycuber` to a solved cube and checked exactly which grid row/column of each neighbouring face changed colour and to which colour — every result matched the diagram above (e.g. an `L` move turns `U`'s column 0 to B's colour, `F`'s column 0 to U's colour, `D`'s column 0 to F's colour, and `B`'s column **2** to D's colour, confirming B's "wrap-around" column placement).

### Cubie ↔ facelet mapping tables
`Corner` enum: `URF=0, UFL=1, ULB=2, UBR=3, DFR=4, DLF=5, DBL=6, DRB=7`
`Edge` enum: `UR=0, UF=1, UL=2, UB=3, DR=4, DF=5, DL=6, DB=7, FR=8, FL=9, BL=10, BR=11`
`Color` enum (also face indices): `U=0, R=1, F=2, D=3, L=4, B=5`

```python
# corner position -> its 3 facelet indices, in (U/D-facelet, second, third) order
cornerFacelet = [
    [U9,R1,F3], [U7,F1,L3], [U1,L1,B3], [U3,B1,R3],
    [D3,F9,R7], [D1,L9,F7], [D7,B9,L7], [D9,R9,B7],
]
# edge position -> its 2 facelet indices
edgeFacelet = [
    [U6,R2], [U8,F2], [U4,L2], [U2,B2], [D6,R8], [D2,F8],
    [D4,L8], [D8,B8], [F6,R4], [F4,L6], [B6,L4], [B4,R6],
]
# corner cubie identity -> its 3 home-face colours, matching cornerFacelet's index order
cornerColor = [
    [U,R,F], [U,F,L], [U,L,B], [U,B,R],
    [D,F,R], [D,L,F], [D,B,L], [D,R,B],
]
# edge cubie identity -> its 2 home-face colours, matching edgeFacelet's index order
edgeColor = [
    [U,R], [U,F], [U,L], [U,B], [D,R], [D,F], [D,L], [D,B],
    [F,R], [F,L], [B,L], [B,R],
]
```
(`U9`, `R1`, etc. are the facelet indices from the layout above, e.g. `U9 = 8`, `R1 = 9`.) To render a cubie-level state `(cp, co, ep, eo)` as a 54-char facelet string: fill the 6 centers (`U5,R5,F5,D5,L5,B5`) with their own face colour, then for each corner position `i`, the cubie sitting there is `cp[i]` with orientation `co[i]`, so facelet `cornerFacelet[i][(k+co[i])%3]` gets colour `cornerColor[cp[i]][k]` for `k=0,1,2`; symmetrically for edges with mod 2. This exact procedure (I reimplemented it and ran it — see §3) reproduces `to_facelet_cube()` from `hkociemba`'s `cubie.py`.

Face-turn permutation tables for the 6 basic clockwise moves (`cp`/`co`/`ep`/`eo`, i.e. "which cubie ends up in each position, with what orientation change, after one clockwise turn of a solved cube") are also taken verbatim from `cubie.py` and are available in the scratch script the programmer can reuse (`cube_verify.py`, described in §3) rather than retyped here — they're 6 arrays of 8 and 6 arrays of 12 integers.

---

## 3. Test vectors

All computed and cross-validated by two independent implementations:
1. **Ground-truth engine**: reimplemented Kociemba's own `corner_multiply`/`edge_multiply` group-composition logic verbatim from `cubie.py`, using the tables in §2, applying moves via right-multiplication (`state := state * move`) starting from the identity cube — exactly mirrors how `hkociemba`'s own move-table generator composes moves.
2. **`pycuber`**, translated into Kociemba order via the colour map and orientation confirmed in §2.

Both engines produced **byte-identical facelet strings** for every case below. Each was also fed to `kociemba.solve()` as a third, independent sanity check.

| Sequence | Facelet string (Kociemba order U R F D L B) | `kociemba.solve()` result |
|---|---|---|
| *(solved)* | `UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB` | `""` (0 moves) |
| `R` | `UUFUUFUUFRRRRRRRRRFFDFFDFFDDDBDDBDDBLLLLLLLLLUBBUBBUBB` | `R'` (1 move) |
| `U` | `UUUUUUUUUBBBRRRRRRRRRFFFFFFDDDDDDDDDFFFLLLLLLLLLBBBBBB` | `U'` (1 move) |
| `F` | `UUUUUULLLURRURRURRFFFFFFFFFRRRDDDDDDLLDLLDLLDBBBBBBBBB` | `F'` (1 move) |
| `R U R' U'` | `UULUUFUUFRRUBRRURRFFDFFUFFFDDRDDDDDDBLLLLLLLLBRRBBBBBB` | `U R U' R'` (4 moves — the exact group inverse) |
| Superflip (all 12 edges flipped in place, corners untouched — standard definition, e.g. [Wikipedia](https://en.wikipedia.org/wiki/Superflip)) | `UBULURUFURURFRBRDRFUFLFRFDFDFDLDRDBDLULBLFLDLBUBRBLBDB` | 21-move solution (two-phase isn't optimal; superflip's proven optimal is 20 moves, so 21 from a "good enough" two-phase solve is expected and consistent) |
| Checkerboard, `M2 E2 S2` (a.k.a. "Pons Asinorum" — [pattern reference](https://www.speedsolving.com/wiki/index.php/List_of_pretty_patterns)) | `UDUDUDUDURLRLRLRLRFBFBFBFBFDUDUDUDUDLRLRLRLRLBFBFBFBFB` | `U2 D2 R2 L2 F2 B2` (6 moves — a nice bonus: confirms the well-known alternate outer-turn-only recipe for the same pattern) |

### Move-order confirmations
Computed by repeatedly composing each sequence (via the ground-truth engine) until the cubie state returns to identity:

| Sequence | Order |
|---|---|
| `R U` | 105 |
| `R U R' U'` | 6 |
| `R U2 D' B D'` | 1260 |

All three match the values given in the assignment exactly (105 and 1260 are also independently attested at [speedsolving.com](https://www.speedsolving.com/threads/possible-orders-of-rubiks-cube-positions.23185/) and general Rubik's-cube-group-theory references; 1260 = lcm(28,45) from a bad 5-cycle+3-cycle of corners and a bad 7-cycle+two-swap of edges).

**For the programmer:** the verification script (ground-truth engine + move-order checker) is at `/private/tmp/.../scratchpad/cube_verify.py` from this session — it's throwaway/reference code, not meant to be reused as-is, but it's a good starting skeleton for the corner/edge cubie-level engine described in §4, and a good source of already-correct move tables to type from rather than re-deriving by hand.

---

## 4. Random-state scramble algorithm

**Group size**: 8! × 3⁷ × (12!/2) × 2¹¹ = 43,252,003,274,489,856,000, matching the number in the project brief (standard result, e.g. [Wikipedia: Rubik's Cube group](https://en.wikipedia.org/wiki/Rubik%27s_Cube_group)). The `/2` reflects that corner permutation parity must equal edge permutation parity — that's the *only* combinatorial constraint linking the two; corner twist and edge flip are each independently constrained only by their own parity sum.

### Algorithm (uniform sampling)
1. **Corner permutation**: draw a uniformly random permutation of the 8 corners (e.g. Fisher–Yates over `[URF,UFL,ULB,UBR,DFR,DLF,DBL,DRB]`). Note its parity (even/odd).
2. **Corner orientation**: draw each of 7 corners' twist uniformly from `{0,1,2}`; set the 8th so the sum ≡ 0 (mod 3). (This is exactly `set_twist()` in `hkociemba`'s `cubie.py`, which does this via a base-3 digit expansion — reusable as-is.)
3. **Edge permutation**: draw a uniformly random permutation of the 12 edges, **then fix its parity to match the corner permutation's parity from step 1** — the simplest correct fix is: if parities don't match, swap any two edges (e.g. the last two) once, which always flips edge-permutation parity without touching corner permutation. This "generate-then-fix" approach needs only one shuffle (vs. an average of ~12 reshuffles for naive rejection sampling of the joint permutation — the "reassemble and reject" vs "reassemble and fix" distinction is exactly this; see the discussion referenced in [arxiv 2410.20630](https://arxiv.org/pdf/2410.20630) and standard cube-group-theory notes such as [Tom Davis, "Group Theory via Rubik's Cube"](http://www.geometer.org/rubik/group.pdf)) and still yields a uniform distribution over the constrained set, since a single transposition is a parity-preserving-or-flipping bijection on the "wrong half" of S₁₂.
4. **Edge orientation**: draw each of 11 edges' flip uniformly from `{0,1}`; set the 12th so the sum ≡ 0 (mod 2). (Exactly `set_flip()` in `cubie.py`.)
5. **Convert to facelet string** using the `cornerFacelet`/`edgeFacelet`/`cornerColor`/`edgeColor` tables from §2 (identical procedure to rendering any cubie state as facelets — no special-casing needed for a random one).

This produces one of the 43,252,003,274,489,856,000 legal states with exactly uniform probability, entirely by construction — no rejection loop is needed at all if step 3's parity-fix is applied (matching the project brief's "Scramble is always legal by construction").

Note this scramble method **does not by itself produce a move sequence** — it directly constructs a legal cubie/facelet state. If the tool ever wants to *display* the scramble as a move sequence (WCA-style), that's a separate, harder problem (find *some* sequence reaching that state, typically by running the two-phase solver on the state and reversing/inverting its solution) — out of scope unless requested, since the project brief's `scramble` command sets state directly.

`scramble N` (N-move scramble, no consecutive same-face moves) is unrelated to the above — it's just N random face-turn tokens drawn from `{U,D,R,L,F,B}×{'', ', 2}` with a same-face-as-previous check, applied via the move-composition logic from §2/§3.

---

## 6. Headless Claude Code (`claude -p`) locked to one MCP server

*(Requested by orchestrator as an added item, priority ahead of §5; also sent directly to `programmer`.)*

Source: official docs at [code.claude.com/docs/en/headless](https://code.claude.com/docs/en/headless), [.../en/mcp](https://code.claude.com/docs/en/mcp), and [.../en/cli-reference](https://code.claude.com/docs/en/cli-reference).

### (a) Load only our MCP server
```bash
claude -p --strict-mcp-config --mcp-config ./mcp.json "your prompt"
```
`--mcp-config <path-or-json>` loads MCP servers from a JSON file (or inline JSON string). `--strict-mcp-config` makes Claude Code use **only** the servers passed via `--mcp-config` for that invocation — it skips all user-, project-, and local-scope servers from `~/.claude.json`/`.mcp.json`, and skips plugin-provided servers and claude.ai connectors too. This is the combination for CI/reproducible headless runs.

`mcp.json` shape for a stdio Python server:
```json
{
  "mcpServers": {
    "rubiks-cube": {
      "type": "stdio",
      "command": "python3",
      "args": ["/absolute/path/to/server.py"],
      "env": {}
    }
  }
}
```
Resulting tools are callable as `mcp__rubiks-cube__<tool_name>`.

Also add `--bare` to skip auto-discovery of hooks/skills/custom-commands/plugins/other MCP servers/CLAUDE.md/auto-memory entirely — recommended for CI so nothing from the host environment leaks in. Note: bare mode doesn't read OAuth/keychain credentials, so `ANTHROPIC_API_KEY` must be set in the environment (relevant since the brief says "no API key" — **if there's genuinely no key, don't use `--bare`**, since `-p` without `--bare` uses the normal subscription login instead).

### (b) Disable all built-in tools so only our MCP tools are callable
Two independent knobs, both needed:
- **`--tools <list>`** restricts the session's *built-in* tools to exactly the ones named — pass an empty/omitted list (or a list that excludes Bash/Read/Write/WebFetch/etc.) to leave none of them available. This is a hard restriction, unlike `--allowedTools` below.
- **`--strict-mcp-config` + `--mcp-config`** (from (a)) restricts which *MCP* servers/tools exist at all.
- **`--allowedTools`/`--disallowedTools`** only pre-approve or deny specific tools for the permission system — they don't remove a tool's *availability*, they just decide whether it prompts. ⚠️ Two open Claude Code issues worth knowing about before relying on them for MCP tools specifically: [#12863](https://github.com/anthropics/claude-code/issues/12863) (`--disallowedTools` reported not affecting MCP server tools in `-p` mode) and [#20617](https://github.com/anthropics/claude-code/issues/20617) (allow/disallow rules in `.mcp.json` reportedly ignored). Given that, prefer `--tools` (hard restriction on built-ins) + `--strict-mcp-config` (hard restriction on which MCP servers load) as the actual security boundary, and use allow-rules only to silence prompts, not to enforce restriction.

To **pre-approve our MCP tools so `-p` never blocks on a prompt**, add an allow rule (in `.claude/settings.json`, or passed via `--settings`) matching the tool name pattern:
```json
{ "permissions": { "allow": ["mcp__rubiks-cube__*"] } }
```
or pass `--permission-mode bypassPermissions` for a fully-trusted sandboxed run (no prompts at all — use only if the MCP server itself is trusted, since this also bypasses everything else). `--permission-mode dontAsk` is the safer unattended default: denies anything that isn't explicitly allow-ruled instead of bypassing everything.

### (c) System prompt, model, turns, output capture
```bash
claude -p --strict-mcp-config --mcp-config ./mcp.json \
  --tools "" \
  --append-system-prompt "You are solving a Rubik's Cube. Only call rubiks-cube tools." \
  --model claude-sonnet-5 \
  --max-turns 200 \
  --output-format json \
  "Solve the cube using the tools available."
```
- `--append-system-prompt "<text>"` (or `--append-system-prompt-file <path>`) appends to the default system prompt; `--system-prompt "<text>"` replaces it outright.
- `--model <alias-or-name>` — aliases `sonnet`/`opus`/`haiku`/`fable`, or a full name like `claude-sonnet-5`.
- `--max-turns <n>` caps agentic turns in print mode; exits with an error at the limit (no limit by default) — useful as a hard budget for a solve attempt.
- `--output-format json` returns one JSON object with `result` (final text), `session_id`, and (per the docs) `total_cost_usd` plus a per-model cost breakdown — exactly what's needed to log cost/usage per solve attempt. `stream-json` gives newline-delimited events instead, ending in a `result` message with the same fields, useful if you want per-move streaming rather than a single blob.

### (d) Minimal Python `mcp` SDK (official, not the third-party `fastmcp` PyPI package) stdio server
```bash
pip install mcp
```
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("rubiks-cube")

@mcp.tool()
def move(notation: str) -> str:
    """Apply one or more cube moves (e.g. 'R U2 F\\'') and return the new state as text."""
    try:
        new_state = apply_moves(notation)   # your engine
        return render_state(new_state)
    except InvalidMoveError as e:
        raise ValueError(str(e))  # FastMCP turns a raised exception into an error result automatically

if __name__ == "__main__":
    mcp.run(transport="stdio")
```
For explicit control over the error flag (rather than relying on an exception), the lower-level return type is:
```python
from mcp.types import CallToolResult, TextContent

return CallToolResult(
    content=[TextContent(type="text", text="Invalid move: I is not a face")],
    isError=True,
)
```
`isError=True` is how a tool signals a domain-level failure (e.g. "not a legal move") without it being a protocol/transport error — the model sees the text content and knows to retry with a different move, which is exactly the "invalid input is rejected with an error and does not change state" behavior the brief specifies.

---

## 5. Prior work on LLMs + Rubik's Cube

*(Sent directly to `designer` as well, since it bears on the LLM-facing state format.)*

**Headline finding across everything found: pure LLM text-based solving of a full 3×3×3 from a nontrivial scramble is essentially unsolved without external search/RL assistance. Success drops off very fast with scramble depth, regardless of representation.**

- **[Cube Bench](https://arxiv.org/abs/2512.20595)** (2025) — the most directly relevant benchmark. Tests 7 MLLMs on 5 skills: reconstructing cube faces from image+text, picking the optimal next move, predicting a move's outcome *without* applying it, executing multi-step plans while recovering from mistakes, and self-detecting/revising errors. Findings: accuracy drops sharply with depth; once a trajectory stalls or diverges, models rarely recover; high face-reconstruction accuracy does **not** predict good move selection or execution; a large closed-source vs. open-source gap on both perception and control. Directly validates the project's "turn-based, feed state back after every move" design — the benchmark itself treats per-move state feedback and error recovery as the core hard skills to measure.
- **["Empirical Evidence of Complexity-Induced Limits..."](https://arxiv.org/pdf/2604.13371)** (2026) tests 9 classical reasoning tasks including Rubik's Cube with deterministic validators (only fully-valid solutions accepted). Finds a "reasoning collapse" pattern: high accuracy at low complexity, sharp degradation past a task-specific threshold, with constraint violations and **state-tracking failures** as a named failure mode, and longer reasoning traces do not reliably help. This is a strong argument for keeping the text state representation as unambiguous and low-parse-burden as possible (a fixed-order, fixed-width string beats anything requiring the model to infer structure).
- **["Puzzle Solving using Reasoning of LLMs: A Survey"](https://arxiv.org/html/2402.11291v2)** (2024) — a GPT-2 fine-tuned on 2,400+ Rubik's Cube samples solved only 1/7 single-shot attempts, and many "generated moves were syntactically valid but logically incorrect" — i.e., the model could produce well-formed notation while still losing track of the actual cube state, reinforcing that notation validity and state-tracking correctness are separate failure modes to test independently. For 2×2×2 (much smaller state space), "Everything of Thoughts" (XoT, MCTS-augmented tree search over LLM "thoughts") reached 77.6% success on GPT-3.5/GPT-4 — but that's with external search assistance, not the model solving unaided turn-by-turn.
- **[Everything of Thoughts](https://arxiv.org/abs/2311.04254)** (2023), the paper behind that XoT result: explicitly leans on pretrained RL + MCTS bolted onto the LLM, and even then only handled cube states solvable within 4 moves (their test set was capped at 4-step scrambles). Illustrates the current ceiling for tool/search-assisted setups on toy-sized versions of the problem — full 3×3×3 optimal solutions run to ~20 moves, well beyond this.
- **[On Solving the Rubik's Cube with Domain-Independent Planners](https://arxiv.org/abs/2307.13552)** (2023) — not LLM-specific, but directly relevant to state representation: introduces the first PDDL (predicate-based) encoding of the cube for general planners, compared against SAS+ and DeepCubeA's custom representation. DeepCubeA (custom repr.) solved all test cases (78.5% optimal); Scorpion/SAS+ solved 61.5% optimally; FastDownward/PDDL solved 56.5% (of which 79.6% were optimal when found). Takeaway: representation choice measurably affects solver success even for non-LLM planners, so it's worth treating the facelet-string format itself as a variable worth testing, not a foregone conclusion.
- Representations seen in the broader (mostly non-LLM, RL-focused) literature, for context on the design space: a 324-dim one-hot vector (6 colours × 54 stickers) for DeepCubeA-style RL nets; a raw 54-character string of digits 0–5 with face separators; a 54-letter string using colour-initial tokens (`b,g,o,r,w,y`). None of these is obviously better *for an LLM specifically* in what was found — the Kociemba-style fixed-order `URFDLB` facelet string (already decided in the project brief) is a reasonable, well-precedented choice and has the advantage (per the complexity-limits paper's diagnosis of state-tracking failure) of being maximally regular/parseable.
- Not a study but worth knowing about: [Gwern's "On the Impossibility of Superintelligent Rubik's Cube Solvers"](https://gwern.net/rubiks-cube) is a satirical essay *generated by* Claude 3.5, not an actual experiment — despite the on-topic title it contains no real cube-solving data and shouldn't be cited as evidence either way.

**Synthesis / recommendation for the LLM-facing format** (my own read, not directly sourced from any one paper): favor a single fixed-order 54-character facelet string over any nested/nested-list or nested-nested nested representation, keep it identical between the model's output during "predict the outcome" style prompts and the state you actually feed back, and expect — based on every benchmark above — that success will fall off a cliff somewhere past a small number of scrambling moves regardless of format; the interesting measurement is *where* that cliff is and whether feeding the state back every turn (vs. asking for a full plan up front) pushes it further out.
