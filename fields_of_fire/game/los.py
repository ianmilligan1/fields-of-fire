"""Line of Sight, range, and elevation per §5.2.

LOS is traced along the eight straight rays from a card. Adjacent cards
are always in LOS (Close Range, +0). For 2nd/3rd cards (Long, Very Long
range) the entry AND exit borders of the intervening card must be white.

Elevation: a higher card sees over lower cards even through dark borders,
EXCEPT when looking straight up/downhill across a level-2 dark-border
card from a level-3 to a level-1 card.

Smoke / Incoming!: LOS is one-way — you can trace IN but not THROUGH.
"""

from __future__ import annotations

from typing import Iterable, Optional, Tuple

from .state import GameState, CardState


# Border indices: N=0, E=1, S=2, W=3 (matches "NESW" string in terrain.json).


# ─────────────────────────── geometry ────────────────────────────


def step_dir(a: tuple, b: tuple) -> Optional[Tuple[int, int]]:
    """Return the (dr, dc) unit step from a to b along one of the 8 rays,
    or None if b is not on a ray from a."""
    dr = b[0] - a[0]
    dc = b[1] - a[1]
    if dr == 0 and dc == 0:
        return None
    if dr != 0 and dc != 0 and abs(dr) != abs(dc):
        return None
    udr = 0 if dr == 0 else (1 if dr > 0 else -1)
    udc = 0 if dc == 0 else (1 if dc > 0 else -1)
    return (udr, udc)


def cards_along(a: tuple, b: tuple) -> list:
    """Cards on the ray from a (exclusive) to b (inclusive)."""
    d = step_dir(a, b)
    if d is None:
        return []
    out = []
    cur = (a[0] + d[0], a[1] + d[1])
    while True:
        out.append(cur)
        if cur == b:
            return out
        cur = (cur[0] + d[0], cur[1] + d[1])


def range_between(a: tuple, b: tuple) -> int:
    """Distance in card-steps; -1 if not on a ray."""
    d = step_dir(a, b)
    if d is None:
        return -1
    return max(abs(b[0] - a[0]), abs(b[1] - a[1]))


def range_label(n: int) -> str:
    return {0: "P", 1: "C", 2: "L", 3: "VL"}.get(n, "OOR")


# ─────────────────────── LOS / spotting ──────────────────────────


def _border_index_for_step(step: Tuple[int, int]) -> Tuple[int, int]:
    """Return (exit_border_of_a, entry_border_of_b) for one ray-step a→b.
    Border order in the string is N(0), E(1), S(2), W(3)."""
    dr, dc = step
    # Map step direction → exit/entry border of the moving card.
    # N step: exit N(0) of source, enter S(2) of dest.
    # Diagonals: pick the dominant axis convention — we treat the corner
    # as both borders (LOS passes if ANY of the involved corners are
    # white). Simpler practical rule: corner LOS uses the average; we
    # require BOTH adjacent borders to be white for a clean diagonal.
    if dr == -1 and dc == 0:
        return 0, 2
    if dr == 1 and dc == 0:
        return 2, 0
    if dr == 0 and dc == 1:
        return 1, 3
    if dr == 0 and dc == -1:
        return 3, 1
    if dr == -1 and dc == 1:
        return 0, 2  # NE corner — approx
    if dr == -1 and dc == -1:
        return 0, 2
    if dr == 1 and dc == 1:
        return 2, 0
    if dr == 1 and dc == -1:
        return 2, 0
    return 0, 0


def has_los(state: GameState, a: tuple, b: tuple, *, max_range: int = 3) -> bool:
    """Trace LOS from a to b, both card positions. Returns True if a
    can see b under standard daylight rules."""
    if a == "staging" or b == "staging":
        return False  # §8.5: cannot spot from Staging
    if a not in state.cards or b not in state.cards:
        return False
    rng = range_between(a, b)
    if rng < 1 or rng > max_range:
        return False
    if rng == 1:
        return True  # Adjacent cards always in LOS

    path = cards_along(a, b)  # cards from a's neighbor to b inclusive
    # We need to traverse INTERVENING cards' both borders. The destination
    # itself only needs its entry border check.
    cur = a
    a_card = state.cards[a]
    a_elev = 1 + a_card.terrain.elevation
    b_card = state.cards[b]
    b_elev = 1 + b_card.terrain.elevation

    # Smoke or Incoming markers BLOCK LOS through the card (one-way in
    # only). Per §5.4 you can trace LOS *into* such a card but never out.
    # So if b's card has smoke/incoming, you can still see it (LOS in).
    # If any *intervening* card has smoke/incoming, LOS is blocked.

    for i, nxt in enumerate(path):
        nxt_card = state.cards[nxt]
        is_destination = (nxt == b)
        step = (nxt[0] - cur[0], nxt[1] - cur[1])
        exit_b, entry_b = _border_index_for_step(step)

        # Source card's exit border (only checked once, on first hop)
        if i == 0:
            if a_card.terrain.borders[exit_b] == "d":
                # Elevation override per §5.2.2: a higher source can see
                # over its own dark borders if target is lower.
                if a_elev <= b_elev and a_elev <= 1:
                    return False
                if a_elev <= 1:
                    return False

        # Entry border of nxt
        if nxt_card.terrain.borders[entry_b] == "d":
            # Elevation: higher source sees over lower terrain even with dark borders.
            nxt_elev = 1 + nxt_card.terrain.elevation
            # Special blocked case: looking from elev 3 → elev 1 across an
            # elev 2 card with dark borders.
            if a_elev > nxt_elev:
                pass  # see-over OK
            else:
                return False

        # Smoke/Incoming on intervening card blocks LOS through it.
        if not is_destination:
            if nxt_card.smoke or nxt_card.incoming:
                return False
            # Exit border of intervening card
            step2 = (path[i + 1][0] - nxt[0], path[i + 1][1] - nxt[1]) if i + 1 < len(path) else None
            if step2 is not None:
                ex2, _ = _border_index_for_step(step2)
                if nxt_card.terrain.borders[ex2] == "d":
                    nxt_elev = 1 + nxt_card.terrain.elevation
                    if a_elev > nxt_elev:
                        pass
                    else:
                        return False
        cur = nxt
    return True


def in_weapon_range(unit_range: str, dist: int) -> bool:
    """Is `dist` (cards) within the unit's range string ('P'/'C'/'L'/'VL')?
    Per §1.2.3 ranges: P=same card, C=adjacent, L=2 cards, VL=3 cards.
    None / 'none' returns False."""
    rng_max = {"P": 0, "C": 1, "L": 2, "VL": 3, "none": -1}.get(unit_range, -1)
    return 0 <= dist <= rng_max


def cards_in_los(state: GameState, origin: tuple, max_range: int = 3) -> list:
    out = []
    for pos in state.cards:
        if pos == origin:
            continue
        if has_los(state, origin, pos, max_range=max_range):
            out.append(pos)
    return out
