"""Loaders for Action / Terrain / Unit / Enemy data, and game setup.

§2 Preparing for a Mission. The Normandy Mission 1 setup is hardcoded
here — 4 cols × 3 rows face-up, US Rifle Company in the Staging Area,
PC markers placed per the mission instructions.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from . import state as gs


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def load_action_deck() -> list:
    raw = json.loads((DATA_DIR / "action_deck.json").read_text())
    return list(raw["cards"])


def load_terrain_deck() -> list:
    raw = json.loads((DATA_DIR / "terrain.json").read_text())
    expanded = []
    for entry in raw["deck"]:
        for _ in range(entry.get("weight", 1)):
            expanded.append(entry)
    return expanded


def load_units() -> dict:
    return json.loads((DATA_DIR / "units.json").read_text())


# ───────────────────────── mission setup ─────────────────────────


def setup_mission(rng: random.Random) -> gs.GameState:
    """Set up Normandy Mission 1-style offensive: 4×3 face-up map,
    Primary Objective in (R3,C2), Attack Position (R2,C2), Line of
    Departure between Row 1 and Staging.
    """
    state = gs.GameState(rng=rng)
    state.action_deck = load_action_deck()
    rng.shuffle(state.action_deck)

    # Build map
    terrain_deck = load_terrain_deck()
    rng.shuffle(terrain_deck)
    deck_iter = iter(terrain_deck)
    for r in range(1, state.map_rows + 1):
        for c in range(1, state.map_cols + 1):
            t_dict = next(deck_iter)
            terrain = gs.TerrainCard.from_dict(t_dict)
            cs = gs.CardState(terrain=terrain)
            # Stack a second card on top of a Hill (per §2.2.1, §5.2.2A).
            if terrain.elevation > 0:
                top = next(deck_iter)
                while gs.TerrainCard.from_dict(top).elevation > 0:
                    top = next(deck_iter)
                cs.terrain = gs.TerrainCard.from_dict({**top, "elevation": terrain.elevation})
            state.cards[(r, c)] = cs

    # Tactical Control markers
    state.cards[state.objective].tac_controls.append("OBJ")
    state.cards[state.attack_position].tac_controls.append("AP")
    for c in range(1, state.map_cols + 1):
        # Left/Right boundaries are columns 1 and 4 walls (implicit).
        # Line of Departure is between row 0 (staging) and row 1.
        # Limit of Advance is the top of row 3 — implicit.
        pass

    # PC markers — Mission 1 places A on row 3, B on row 2, C on row 1
    # (the deeper into enemy territory, the more severe).
    for r in range(1, state.map_rows + 1):
        letter = {1: "C", 2: "B", 3: "A"}[r]
        for c in range(1, state.map_cols + 1):
            # Don't auto-place on the AP — the player plans to seize it.
            state.cards[(r, c)].pc_marker = letter

    # US units — load TO&E, place all in staging
    udata = load_units()["us_company"]

    def make(d: dict) -> gs.Unit:
        return gs.Unit(
            uid=d["id"], name=d["name"], side=gs.SIDE_US,
            vof=d["vof"], range_=d["range"],
            exp=d["exp"], steps=d["steps"], max_steps=d["steps"],
            is_hq=d.get("is_hq", False),
            is_fo=d.get("is_fo", False),
            fo_type=d.get("fo_type", ""),
            weapon_type=d.get("weapon_type", ""),
            tier=d.get("tier", ""),
            platoon=d.get("platoon", ""),
            ammo=d.get("ammo"),
        )

    for d in udata["hqs"]:
        state.units.append(make(d))
    for d in udata["squads"]:
        state.units.append(make(d))
    for d in udata["weapons"]:
        state.units.append(make(d))
    for d in udata["company_weapons"]:
        state.units.append(make(d))
    for d in udata["spotters"]:
        state.units.append(make(d))

    # Fire Missions
    fm_meta = load_units()["fire_missions"]
    state.fire_missions = {k: v["available"] for k, v in fm_meta.items() if isinstance(v, dict)}

    return state
