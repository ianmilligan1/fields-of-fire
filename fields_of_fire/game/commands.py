"""Action menus and command-point spending per §4.2.

Player-facing actions are dispatched here. Each takes (state, originator,
prompts) and consumes Command points. Returns True if action was taken.

This module is UI-aware in that it imports `ui.prompts` to ask the
player for choices when needed, but it doesn't print itself.
"""

from __future__ import annotations

from typing import Optional

from . import state as gs
from .state import (
    GameState, Unit, VOFMarker, PDFMarker,
    SIDE_US, SIDE_GER, VOF_VALUES,
    STATUS_GOOD, STATUS_PINNED, STATUS_CASUALTY,
    LAT_FIRE, LAT_ASSAULT, LAT_LITTER, LAT_PARALYZED,
    EXP_GREEN, EXP_LINE, EXP_VETERAN,
)
from .los import has_los, range_between, in_weapon_range, cards_in_los
from . import combat


# ─── Command-draw modifiers per §4.1.2 ───


def command_draw_modifier(state: GameState, hq: Unit) -> int:
    mod = 0
    if hq.pinned:
        mod -= 1
    if hq.exp == EXP_GREEN:
        mod -= 1
    elif hq.exp == EXP_VETERAN:
        mod += 1
    if hq.cover_marker:
        mod += 1
    cs = state.card(hq.pos) if hq.pos != "staging" else None
    if cs:
        # Best (lowest) VOF affecting the card
        worst = None
        for v in cs.vofs:
            if worst is None or v.value < worst:
                worst = v.value
        if worst is not None:
            if worst <= -3:
                mod -= 3
            elif worst <= -1:
                mod -= 2
            elif worst <= 0:
                mod -= 1
    if state.activity == gs.ACTIVITY_NO_CONTACT:
        mod += 1
    return mod


def saved_command_cap(hq: Unit) -> int:
    """§4.1.3 — daytime caps."""
    return {EXP_GREEN: 3, EXP_LINE: 6, EXP_VETERAN: 9}.get(hq.exp, 6)


def per_impulse_cap(state: GameState) -> int:
    return 6 if state.visibility == gs.VIS_DAYLIGHT else 4


# ─── action draw with modifiers ───


def _draws_for_action(state: GameState, recipient: Unit, base: int) -> int:
    """Modify the base draw count by Recipient experience (Movement/Combat)."""
    n = base
    if recipient.exp == EXP_VETERAN:
        n += 1
    elif recipient.exp == EXP_GREEN:
        n -= 1
    return max(1, n)


# ──────────────────────── Movement Actions (§4.2.2) ──────────────────


def move_to_adjacent(state: GameState, originator: Unit, recipient: Unit, dest: tuple) -> bool:
    """§4.2.2a — automatic, costs 1 command."""
    if recipient.exposed:
        state.emit(f"{recipient.name} cannot Move (Exposed).")
        return False
    if recipient.pos == "staging":
        # Entering map across the LoD into Row 1
        if dest not in state.cards or dest[0] != 1:
            state.emit(f"{recipient.name} can only enter on Row 1 from Staging.")
            return False
    else:
        if range_between(recipient.pos, dest) != 1:
            state.emit(f"{recipient.name}: {dest} is not adjacent.")
            return False
    # Remove old PDFs from old position
    if recipient.pos != "staging":
        cs = state.card(recipient.pos)
        cs.pdfs = [p for p in cs.pdfs if p.origin != recipient.pos]
        # Move VOFs targeting only this unit on its old card with it? Skip for MVP.
    recipient.pos = dest
    recipient.exposed = True
    recipient.cover_marker = None
    state.emit(f"{recipient.name} moves to {dest} — Exposed.")
    # Re-evaluate Open Fire for everyone (§6.0)
    combat.open_fire_all(state)
    state.update_activity()
    return True


def attempt_seek_cover(state: GameState, originator: Unit, recipient: Unit) -> bool:
    """§4.2.2e — draw equal to card's Cover Draw, look for 'cover' icon."""
    cs = state.card(recipient.pos)
    if cs is None:
        return False
    if recipient.cover_marker:
        state.emit(f"{recipient.name} already in cover.")
        return False
    if cs.terrain.cover_potential <= len(cs.covers):
        state.emit(f"{recipient.pos} cover potential exhausted.")
        return False
    n = _draws_for_action(state, recipient, cs.terrain.cover_draws)
    cards = state.draw_cards(n)
    if any(c["icons"].get("cover") for c in cards):
        marker_id = f"cover_{recipient.pos[0]}_{recipient.pos[1]}_{len(cs.covers)+1}"
        from .state import CoverMarker
        cm = CoverMarker(cover_id=marker_id, value=1, type_="basic")
        cs.covers.append(cm)
        recipient.cover_marker = marker_id
        recipient.exposed = True
        state.emit(f"{recipient.name} finds cover at {recipient.pos} (+1).")
        return True
    state.emit(f"{recipient.name} fails to find cover.")
    return False


# ──────────────────────── Combat Actions (§4.2.4) ──────────────────


def attempt_spot(state: GameState, originator: Unit, recipient: Unit, target_pos: tuple) -> bool:
    """§4.2.4a — 2 cards modified by spotting modifiers, look for crosshairs."""
    if not has_los(state, recipient.pos, target_pos):
        state.emit(f"{recipient.name} has no LOS to {target_pos}.")
        return False
    targets = [u for u in state.units_on(target_pos, SIDE_GER) if not u.spotted]
    if not targets:
        state.emit(f"No unspotted enemies at {target_pos}.")
        return False
    # Spot modifiers (§8.5)
    base = 2
    n = _draws_for_action(state, recipient, base)
    # Cover & concealment modifier
    tcs = state.card(target_pos)
    if tcs.terrain.cover_high >= 3:
        n -= 1
    elif tcs.terrain.cover_high == 0:
        n += 1
    n = max(1, n)
    cards = state.draw_cards(n)
    if any(c["icons"].get("crosshairs") for c in cards):
        for u in targets:
            u.spotted = True
        state.emit(f"{recipient.name} spots {len(targets)} enemy unit(s) at {target_pos}!")
        combat.open_fire_all(state)
        state.update_activity()
        return True
    state.emit(f"{recipient.name} fails to spot at {target_pos}.")
    return False


def attempt_concentrate_fire(state: GameState, originator: Unit, recipient: Unit, target_unit: Unit) -> bool:
    """§4.2.4b — draw 2 cards (mod by exp), look for crosshairs."""
    if recipient.pos == "staging" or recipient.vof in ("none", ""):
        state.emit(f"{recipient.name} cannot Concentrate Fire.")
        return False
    # Recipient must already be projecting VOF on the target card
    src = state.card(recipient.pos)
    has_pdf = any(p.origin == recipient.pos and p.target == target_unit.pos for p in src.pdfs)
    same_card = recipient.pos == target_unit.pos
    if not has_pdf and not same_card:
        state.emit(f"{recipient.name} not projecting VOF on {target_unit.pos}.")
        return False
    n = _draws_for_action(state, recipient, 2)
    cards = state.draw_cards(n)
    if any(c["icons"].get("crosshairs") for c in cards):
        tcs = state.card(target_unit.pos)
        tcs.concentrated_fire_targets.append(target_unit.uid)
        state.emit(f"{recipient.name} concentrates fire on {target_unit.name}.")
        return True
    state.emit(f"{recipient.name} fails Concentrate Fire on {target_unit.name}.")
    return False


def attempt_grenade_attack(state: GameState, originator: Unit, recipient: Unit, target_pos: tuple) -> bool:
    """§4.2.4d — 2 cards (mod by exp), look for grenade."""
    n = _draws_for_action(state, recipient, 2)
    cards = state.draw_cards(n)
    tcs = state.card(target_pos)
    if any(c["icons"].get("grenade") for c in cards):
        # Place G! VOF on whole card (simplified)
        tcs.vofs.append(VOFMarker(
            vof_type="G!", value=VOF_VALUES["G!"], origin=recipient.pos,
        ))
        state.emit(f"{recipient.name} grenade attack hits {target_pos}!")
        return True
    tcs.grenade_miss = True
    state.emit(f"{recipient.name} grenade attack misses {target_pos}.")
    return False


def call_for_fire(state: GameState, originator: Unit, fo: Unit, mission_type: str, target_pos: tuple) -> bool:
    """§4.2.4i / §7.16. Draws per mission instructions, looks for Burst."""
    if state.fire_missions.get(mission_type, 0) <= 0:
        state.emit(f"No {mission_type} fire missions remaining.")
        return False
    if fo.fo_type != "arty" and mission_type in ("HE", "WP", "BN"):
        state.emit(f"{fo.name} cannot call {mission_type}.")
        return False
    if not has_los(state, fo.pos, target_pos):
        state.emit(f"{fo.name} has no LOS to {target_pos}.")
        return False
    # Use mission-specific draws based on observer experience
    base = {"HE": 3, "WP": 3, "BN": 4}[mission_type]
    n = _draws_for_action(state, fo, base)
    cards = state.draw_cards(n)
    short = any(c["icons"].get("short") for c in cards)
    burst = any(c["icons"].get("burst") or c["icons"].get("burst3") for c in cards)
    if short:
        # Move target one card closer to the observer (§7.16.4)
        if fo.pos != target_pos:
            dr = 0 if fo.pos[0] == target_pos[0] else (1 if fo.pos[0] > target_pos[0] else -1)
            dc = 0 if fo.pos[1] == target_pos[1] else (1 if fo.pos[1] > target_pos[1] else -1)
            new_target = (target_pos[0] + dr, target_pos[1] + dc)
            if new_target in state.cards:
                target_pos = new_target
        state.emit(f"SHORT! Fire mission lands at {target_pos}.")
    if not burst:
        state.emit(f"{fo.name} call for fire failed.")
        return False
    state.fire_missions[mission_type] -= 1
    tcs = state.card(target_pos)
    vof_value = {"HE": -5, "WP": -3, "BN": -5}[mission_type]
    tcs.vofs.append(VOFMarker(
        vof_type="Incoming!" if mission_type != "WP" else "WP!",
        value=vof_value, origin="offmap", pending=True,
    ))
    if mission_type == "WP":
        tcs.smoke = True
    state.emit(
        f"{fo.name} calls {mission_type} on {target_pos}! "
        f"Pending marker placed (missions left: {state.fire_missions[mission_type]})."
    )
    return True


def cease_fire(state: GameState, originator: Unit, recipient: Unit) -> bool:
    if recipient.pos == "staging":
        return False
    cs = state.card(recipient.pos)
    cs.pdfs = [p for p in cs.pdfs if p.origin != recipient.pos]
    # Remove this unit's VOF from anywhere
    for tcs in state.cards.values():
        tcs.vofs = [v for v in tcs.vofs if v.origin != recipient.pos]
    state.emit(f"{recipient.name} ceases fire.")
    # Re-evaluate per §6.3.3
    combat.open_fire_all(state)
    state.update_activity()
    return True


# ──────────────────────── Rally Actions (§4.2.3) ──────────────────


def attempt_remove_pinned(state: GameState, originator: Unit, recipient: Unit) -> bool:
    if not recipient.pinned:
        return False
    cs = state.card(recipient.pos)
    if cs is None or not cs.vofs:
        recipient.pinned = False
        state.emit(f"{recipient.name} unpinned (no VOF, automatic).")
        return True
    n = _draws_for_action(state, originator, 2)
    cards = state.draw_cards(n)
    if any(c["icons"].get("rally") for c in cards):
        recipient.pinned = False
        state.emit(f"{recipient.name} rallies — Pinned removed.")
        return True
    state.emit(f"{recipient.name} fails to rally.")
    return False
