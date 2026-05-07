"""Potential Contact (PC) resolution per §8.2.4 and enemy package
placement per §8.4.

The Potential Contact Draws table (§8.2.4): cross-reference PC letter
against current Activity Level. 'Auto' means immediate contact; a number
means draw that many cards looking for the 'Contact' icon.
"""

from __future__ import annotations

import random

from . import state as gs
from .state import (
    GameState, Unit, CardState, VOFMarker, PDFMarker,
    SIDE_GER, SIDE_US, VOF_VALUES,
)
from .los import has_los, range_between, in_weapon_range
from . import combat


# §8.2.4 Potential Contact Draws table — letter × Activity Level → draws.
# RULEBOOK AMBIGUITY: exact values are on Player Aid card #52, not in the
# rulebook text. These are calibrated to feel right (A is most severe).
PC_DRAWS = {
    "A": {gs.ACTIVITY_NO_CONTACT: "Auto", gs.ACTIVITY_CONTACT: "Auto",
          gs.ACTIVITY_ENGAGED: 1, gs.ACTIVITY_HEAVILY_ENGAGED: 2},
    "B": {gs.ACTIVITY_NO_CONTACT: 1, gs.ACTIVITY_CONTACT: 2,
          gs.ACTIVITY_ENGAGED: 3, gs.ACTIVITY_HEAVILY_ENGAGED: 4},
    "C": {gs.ACTIVITY_NO_CONTACT: 2, gs.ACTIVITY_CONTACT: 3,
          gs.ACTIVITY_ENGAGED: 4, gs.ACTIVITY_HEAVILY_ENGAGED: 5},
}


def _weighted_choice(rng: random.Random, packages: list) -> dict:
    weights = [p["weight"] for p in packages]
    total = sum(weights)
    pick = rng.uniform(0, total)
    acc = 0.0
    for p, w in zip(packages, weights):
        acc += w
        if pick <= acc:
            return p
    return packages[-1]


def _place_at_distance(state: GameState, trigger_pos: tuple, dist_code: str) -> tuple | None:
    """Pick a card at the requested distance from the triggering unit."""
    candidates = []
    for pos in state.cards:
        if pos == trigger_pos:
            if dist_code == "P":
                candidates.append(pos)
            continue
        d = range_between(trigger_pos, pos)
        if d < 0:
            continue
        if dist_code == "P" and d == 0:
            candidates.append(pos)
        elif dist_code == "C" and d == 1:
            candidates.append(pos)
        elif dist_code == "L" and d == 2:
            candidates.append(pos)
        elif dist_code == "VL" and d == 3:
            candidates.append(pos)
        elif dist_code == "MAX":
            # Max LOS reachable (1..3 cards in LOS)
            if 1 <= d <= 3 and has_los(state, trigger_pos, pos):
                candidates.append(pos)
    # Filter: don't place where friendly units are present (§8.4.3)
    valid = []
    for pos in candidates:
        cs = state.card(pos)
        if state.units_on(pos, SIDE_US):
            continue
        if state.units_on(pos, SIDE_GER):
            continue  # don't stack new package on existing enemies
        valid.append(pos)
    if not valid:
        return None
    state.rng.shuffle(valid)
    # Prefer farthest in LOS for MAX, nearest otherwise — keeps ranges sane
    if dist_code == "MAX":
        valid.sort(key=lambda p: -range_between(trigger_pos, p))
    return valid[0]


def _make_enemy_unit(state: GameState, ud: dict, pos: tuple, spotted: bool) -> Unit:
    rng = state.rng
    uid = f"GER_{ud['type']}_{rng.randint(1000, 9999)}"
    return Unit(
        uid=uid, name=ud.get("name", ud["type"]),
        side=SIDE_GER,
        vof=ud.get("vof", "S"),
        range_=ud.get("range", "C"),
        exp=ud.get("exp", "line"),
        steps=ud.get("steps", 1),
        max_steps=ud.get("steps", 1),
        pos=pos, spotted=spotted,
        special=ud.get("type", ""),
        is_fo=ud.get("type") == "ger_mtr_spotter",
        fo_type="mtr" if ud.get("type") == "ger_mtr_spotter" else "",
    )


def _resolve_one_pc(state: GameState, pos: tuple, trigger_unit: Unit, packages: dict) -> None:
    cs = state.card(pos)
    letter = cs.pc_marker
    if letter is None:
        return
    draws_spec = PC_DRAWS[letter][state.activity]
    contact_drawn = (draws_spec == "Auto")
    if not contact_drawn:
        for _ in range(draws_spec):
            card = state.draw_card()
            if card["icons"].get("contact"):
                contact_drawn = True
                break
    cs.pc_marker = None  # remove either way
    if not contact_drawn:
        state.emit(f"PC {letter} at {pos}: no contact.")
        return

    # Pick a package
    pkg_list = packages.get(letter, [])
    if not pkg_list:
        return
    pkg = _weighted_choice(state.rng, pkg_list)
    if pkg.get("special") == "no_contact":
        state.emit(f"PC {letter} at {pos}: no contact (false alarm).")
        return

    # Place units
    for ud in pkg["units"]:
        if ud.get("type") == "mines":
            cs.vofs.append(VOFMarker(vof_type="Mines!", value=VOF_VALUES["Mines!"], origin=pos))
            state.emit(f"PC {letter} at {pos}: MINES! triggered.")
            continue
        if ud.get("type") == "booby_trap":
            # one-shot Booby Trap VOF on the triggering unit
            cs.vofs.append(VOFMarker(vof_type="Booby!", value=VOF_VALUES["Booby!"],
                                      origin=pos, target_unit=trigger_unit.uid))
            state.emit(f"PC {letter} at {pos}: BOOBY TRAP on {trigger_unit.name}!")
            continue
        # Locate destination
        dest = _place_at_distance(state, trigger_unit.pos, pkg.get("distance", "C"))
        if dest is None:
            dest = pos  # fall back to PC card
        spotted = pkg.get("spotted", False)
        u = _make_enemy_unit(state, ud, dest, spotted)
        if pkg.get("special") == "spotter":
            u.fire_mission_count = pkg.get("fire_mission_count", 3)
        state.units.append(u)
        state.emit(
            f"PC {letter} at {pos} → {u.name} ({u.steps}st {u.exp}) "
            f"placed at {dest} {'Spotted' if spotted else 'Unspotted'}."
        )
        if pkg.get("open_fire"):
            combat.open_fire(state, u)
            # Sniper VOF: place Small Arms VOF on whole card too (§7.15)
            if pkg.get("special") == "sniper":
                # already handled by open_fire
                pass
            # Mortar Spotter: queue an Incoming! marker on the trigger card
            if pkg.get("special") == "spotter" and u.fire_mission_count > 0:
                tcs = state.card(trigger_unit.pos)
                if tcs is not None:
                    tcs.vofs.append(VOFMarker(
                        vof_type="Incoming!", value=pkg.get("fire_mission_vof", -3),
                        origin="offmap", pending=False,
                    ))
                    u.fire_mission_count -= 1
                    state.emit(f"Enemy mortar spotter calls fire on {trigger_unit.pos}!")

    state.update_activity()


def evaluate_potential_contacts(state: GameState, packages: dict) -> None:
    """§3.7.2: for each card with a PC marker AND a friendly unit,
    resolve in alphabetical order (A first)."""
    state.emit("─── Potential Contact Evaluation ───")
    candidates = []
    for pos, cs in state.cards.items():
        if cs.pc_marker and state.units_on(pos, SIDE_US):
            candidates.append((cs.pc_marker, pos))
    candidates.sort(key=lambda x: (x[0], state.rng.random()))
    for _, pos in candidates:
        # Pick the triggering unit (first US unit on the card)
        us_units = state.units_on(pos, SIDE_US)
        if not us_units:
            continue
        trigger = us_units[0]
        _resolve_one_pc(state, pos, trigger, packages)
