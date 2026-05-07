"""Combat resolution per §6.

Three principal entry points used by the rest of the engine:

  open_fire(state, firer)  — invoked whenever a unit becomes able to
       fire (§6.0 Basic Combat Principle). Places PDF/VOF on best target.

  resolve_combat_effects(state) — the Combat Effects Segment (§3.7.4 /
       §6.4): for every unit on a card with a VOF, compute NCM, draw a
       card, look up HIT/PIN/MISS, and on HIT draw another card and
       apply Hit Effect from the unit's experience column.

  apply_hit_effect(state, unit, letters) — break down a unit per §6.4.3.
"""

from __future__ import annotations

import random
from typing import Optional

from . import state as gs
from .state import (
    GameState, Unit, VOFMarker, PDFMarker, CardState,
    SIDE_US, SIDE_GER,
    STATUS_GOOD, STATUS_PINNED, STATUS_CASUALTY,
    LAT_FIRE, LAT_ASSAULT, LAT_LITTER, LAT_PARALYZED,
    EXP_GREEN, EXP_LINE, EXP_VETERAN,
    VOF_VALUES,
)
from .los import has_los, range_between, in_weapon_range


# ──────────────────────────── targeting ───────────────────────────


def _eligible_targets(state: GameState, firer: Unit) -> list[tuple]:
    """Return candidate target cards for `firer`. §6.1.1."""
    if firer.pos == "staging":
        return []
    if not firer.can_fire():
        return []
    enemy_side = SIDE_GER if firer.side == SIDE_US else SIDE_US
    out = []
    for pos in state.cards:
        if pos == firer.pos:
            # Point Blank: can fire on jointly-occupied own card
            enemies_here = state.units_on(pos, enemy_side)
            if enemies_here and firer.range_ != "none" and firer.range_ != "":
                # Friendly does NOT auto-fire on jointly occupied (§6.1.1 footnote)
                if firer.side == SIDE_US:
                    continue
                out.append(pos)
            continue
        dist = range_between(firer.pos, pos)
        if not in_weapon_range(firer.range_, dist):
            continue
        if not has_los(state, firer.pos, pos):
            continue
        # Need at least one Spotted enemy (§6.1.1)
        spotted = [u for u in state.units_on(pos, enemy_side) if u.spotted]
        if not spotted:
            continue
        out.append(pos)
    return out


def _pick_target(state: GameState, firer: Unit, targets: list[tuple]) -> Optional[tuple]:
    """Friendly priority: closest, then most steps, then random."""
    if not targets:
        return None
    enemy_side = SIDE_GER if firer.side == SIDE_US else SIDE_US

    def total_steps(pos):
        return sum(u.steps for u in state.units_on(pos, enemy_side))

    if firer.side == SIDE_US:
        targets.sort(key=lambda p: (range_between(firer.pos, p), -total_steps(p)))
        return targets[0]
    else:
        # Enemy: most steps, then card with HQ, then random
        def has_hq(pos):
            return any(u.is_hq or u.is_fo for u in state.units_on(pos, SIDE_US))

        targets.sort(key=lambda p: (-total_steps(p), 0 if has_hq(p) else 1))
        return targets[0]


# ──────────────────────────── VOF mgmt ────────────────────────────


def _firer_vof_marker(firer: Unit) -> VOFMarker:
    if firer.pinned:
        return VOFMarker(vof_type="Pinned", value=VOF_VALUES["Pinned"], origin=firer.pos)
    return VOFMarker(vof_type=firer.vof, value=VOF_VALUES.get(firer.vof, 99), origin=firer.pos)


def open_fire(state: GameState, firer: Unit) -> None:
    """If the firer can engage a target per §6.0/6.1, place PDF/VOF and
    set them as engaged. Idempotent — won't double-place."""
    if firer.status == STATUS_CASUALTY:
        return
    if firer.is_lat() or firer.is_fo or firer.is_hq:
        # HQs/FOs in Normandy MVP have S VOF only when defending Point Blank
        # but in practice we let them open fire if attacked — keep simple.
        if firer.vof in ("none", ""):
            return
    targets = _eligible_targets(state, firer)
    if not targets:
        return
    # If already firing along a PDF, don't re-engage
    for cs in state.cards.values():
        for pdf in cs.pdfs:
            if pdf.origin == firer.pos:
                return
    target = _pick_target(state, firer, targets)
    if target is None:
        return
    src_card = state.card(firer.pos)
    tgt_card = state.card(target)
    if src_card is None or tgt_card is None:
        return
    # Place VOF on target, PDF on firer card
    marker = _firer_vof_marker(firer)
    marker.origin = firer.pos
    tgt_card.vofs.append(marker)
    if firer.pos != target:
        src_card.pdfs.append(PDFMarker(origin=firer.pos, target=target))
    state.emit(f"{firer.name} opens fire on {target} ({marker.vof_type} VOF).")
    state.update_activity()


def open_fire_all(state: GameState) -> None:
    """Re-evaluate Open Fire for every Good Order unit per §6.0."""
    for u in list(state.units):
        if u.pos == "staging" or u.status == STATUS_CASUALTY:
            continue
        open_fire(state, u)


# ─────────────────────────── NCM (§6.4) ───────────────────────────


def _best_vof_affecting(state: GameState, unit: Unit) -> Optional[VOFMarker]:
    """Find the lowest (best for attacker) VOF affecting this unit.
    Per §6.2.1: card-wide VOF + opposing-side VOF + unit-targeted VOF."""
    if unit.pos == "staging":
        return None
    cs = state.card(unit.pos)
    if not cs or not cs.vofs:
        return None
    candidates = []
    for v in cs.vofs:
        # Card-wide VOF from outside affects all units (§6.2.1a)
        if v.target_unit and v.target_unit != unit.uid:
            continue
        # If origin is on this same card and side matches, doesn't apply to self-side
        if v.origin and v.origin != "offmap" and v.origin == unit.pos:
            # Same-card VOF only affects opposing side
            firer = None
            for u in state.units_on(unit.pos):
                if u.uid == unit.uid:
                    continue
                # We can't easily map VOF→firer; approximate by side check
            # Skip for simplicity: same-card VOFs are placed by enemy-side units
            # Will be filtered correctly by side check at placement time
            pass
        candidates.append(v)
    if not candidates:
        return None
    return min(candidates, key=lambda m: m.value)


def _ncm_modifiers(state: GameState, unit: Unit, vof: VOFMarker) -> int:
    """Sum VOF modifiers on the card and unit status modifiers."""
    cs = state.card(unit.pos)
    mod = 0
    # Crossfire (§6.2.4): -1 if 2+ PDFs from outside
    if cs.crossfire:
        mod -= 1
    # Concentrated Fire on this unit
    if unit.uid in cs.concentrated_fire_targets:
        mod -= 1
    # Grenade Miss on the card (§6.2.4): -1 affects whole card
    if cs.grenade_miss:
        mod -= 1
    # Pinned defender: +1 (§4.2.5 footnote on Pinned marker; rule is the
    # +1 modifier when receiving fire)
    if unit.pinned:
        mod += 1
    # Exposed: +2 spot draw modifier, but for combat the +2 from being out
    # of cover and Exposed under indirect/grenade/incoming is implicit
    # via no-cover. We model Exposed as +0 for Basic VOF in MVP.
    # Cover & Concealment from terrain (§5.2.3)
    fire_from_dark = _fire_from_dark_border(state, unit.pos, vof)
    cover_terrain = cs.terrain.cover_high if fire_from_dark else cs.terrain.cover_low
    # Localised VOFs (Grenade, Mines, Sniper, Concentrated): use lower
    # value per rule. Incoming/Air Strike use Burst icon modifier — MVP
    # uses cover_high.
    if vof.vof_type in ("G!", "Mines!", "Booby!"):
        cover_terrain = cs.terrain.cover_low
    if vof.vof_type in ("Incoming!", "WP!"):
        cover_terrain = cs.terrain.cover_low
    mod += cover_terrain
    # Cover marker bonus
    if unit.cover_marker:
        for cm in cs.covers:
            if cm.cover_id == unit.cover_marker:
                mod += cm.value
                break
    return mod


def _fire_from_dark_border(state: GameState, defender_pos: tuple, vof: VOFMarker) -> bool:
    """Check whether any contributing fire crossed a dark border into the
    defender's card. Approximation: if origin and defender are non-
    adjacent, or any border between them is dark, return True."""
    if not vof.origin or vof.origin == "offmap":
        return False  # Indirect / incoming uses cover_low per §5.2.3
    cs = state.card(defender_pos)
    if not cs:
        return False
    dr = defender_pos[0] - vof.origin[0]
    dc = defender_pos[1] - vof.origin[1]
    # Entry border of defender
    if dr == -1 and dc == 0:
        idx = 0
    elif dr == 1 and dc == 0:
        idx = 2
    elif dr == 0 and dc == 1:
        idx = 3
    elif dr == 0 and dc == -1:
        idx = 1
    else:
        return False
    return cs.terrain.borders[idx] == "d"


def compute_ncm(state: GameState, unit: Unit) -> Optional[int]:
    """Return clamped NCM, or None if no VOF affects this unit."""
    vof = _best_vof_affecting(state, unit)
    if not vof:
        return None
    ncm = vof.value + _ncm_modifiers(state, unit, vof)
    return max(-4, min(6, ncm))


# ────────────────────────── Hit Effects ───────────────────────────


def apply_hit_effect(state: GameState, unit: Unit, letters: str) -> list[Unit]:
    """Per §6.4.3, apply a 1- or 2-letter hit effect to the unit. Returns
    any newly created LATs. The original unit is reduced step-by-step.
    """
    new_units: list[Unit] = []
    if unit.steps <= 0 or unit.status == STATUS_CASUALTY:
        return new_units
    for letter in letters:
        if unit.steps <= 0:
            break
        unit.steps -= 1
        lat = _create_lat(state, unit, letter)
        if lat is not None:
            new_units.append(lat)
    # All affected steps Pinned per §6.4.2C
    unit.pinned = True
    if unit.steps <= 0:
        # Original unit is Removed from Play (§1.2.6) only if no LATs
        if not new_units and unit.status != STATUS_CASUALTY:
            unit.status = STATUS_CASUALTY
    state.units.extend(new_units)
    return new_units


def _create_lat(state: GameState, parent: Unit, letter: str) -> Optional[Unit]:
    """Create one LAT from a step. Returns None for C (the step was
    eliminated) — we still record a Casualty unit for evac purposes."""
    counter_id = f"{parent.uid}_{letter}_{state.rng.randint(1000, 9999)}"
    if letter == "C":
        cas = Unit(
            uid=counter_id, name=f"{parent.uid} Casualty", side=parent.side,
            vof="none", range_="none", exp=parent.exp, steps=1, max_steps=1,
            pos=parent.pos, status=STATUS_CASUALTY, spotted=parent.spotted,
        )
        return cas
    # P / L / F / A → set status flag on a 1-step LAT unit
    status_map = {
        "P": LAT_PARALYZED, "L": LAT_LITTER, "F": LAT_FIRE, "A": LAT_ASSAULT,
    }
    status = status_map.get(letter)
    if status is None:
        return None
    # Fire/Assault teams have S/A VOF; Litter/Paralyzed have none
    vof, rng = ("none", "none")
    if status == LAT_FIRE:
        vof, rng = "S", "C"
    elif status == LAT_ASSAULT:
        # Assault Teams have A VOF at Point Blank only — model as S/C in MVP
        vof, rng = "S", "C"
    name_suffix = {LAT_FIRE: "FT", LAT_ASSAULT: "AT", LAT_LITTER: "LT", LAT_PARALYZED: "PT"}[status]
    return Unit(
        uid=counter_id, name=f"{parent.uid}/{name_suffix}", side=parent.side,
        vof=vof, range_=rng, exp=parent.exp, steps=1, max_steps=1,
        pos=parent.pos, status=status, spotted=parent.spotted, pinned=True,
    )


# ───────────────────── Combat Effects Segment ─────────────────────


def resolve_combat_effects(state: GameState) -> None:
    """§3.7.4: for each unit on a card with VOF, compute NCM, draw a
    card, apply HIT/PIN/MISS, and on HIT apply hit effect."""
    state.emit("─── Combat Effects Segment ───")
    # Snapshot units up front: simultaneous resolution, no VOF/PDF updates
    targets = []
    for u in list(state.units):
        if u.pos == "staging" or u.status == STATUS_CASUALTY:
            continue
        cs = state.card(u.pos)
        if cs and cs.vofs:
            targets.append(u)
    for u in targets:
        ncm = compute_ncm(state, u)
        if ncm is None:
            continue
        card = state.draw_card()
        result = card["combat_resolution"][str(ncm)]
        if result == "MISS":
            if u.pinned:
                u.pinned = False
                state.emit(f"{u.name} MISS (NCM {ncm:+d}) — Pinned removed.")
            else:
                state.emit(f"{u.name} MISS (NCM {ncm:+d}).")
        elif result == "PIN":
            u.pinned = True
            state.emit(f"{u.name} PIN (NCM {ncm:+d}).")
        elif result == "HIT":
            effect_card = state.draw_card()
            letters = effect_card["hit_effect"][u.exp]
            state.emit(f"{u.name} HIT (NCM {ncm:+d}) — Effect: {letters} ({u.exp}).")
            apply_hit_effect(state, u, letters)


# ─────────────────────── Pinned Recovery (§3.7.3) ─────────────────


def pinned_recovery(state: GameState) -> None:
    for u in state.units:
        if u.pinned and u.pos != "staging":
            cs = state.card(u.pos)
            if cs and not cs.vofs:
                u.pinned = False
                state.emit(f"{u.name} recovers from Pinned (no VOF).")


# ─────────────────────── Cleanup helpers ──────────────────────────


def clean_up(state: GameState) -> None:
    """§3.8: remove transient markers, exposed flags, etc."""
    for cs in state.cards.values():
        cs.smoke = False
        cs.incoming = False
        cs.crossfire = False
        cs.grenade_miss = False
        cs.concentrated_fire_targets.clear()
    for u in state.units:
        u.exposed = False
        u.activated = False
        u.activity_checked_this_turn = False
    # Saved general initiative pools are zeroed by sequence.py.

    # Award experience for cleared cards
    for pos, cs in state.cards.items():
        us = state.units_on(pos, SIDE_US)
        ger = state.units_on(pos, SIDE_GER)
        if us and not ger and pos not in state.cleared_cards:
            state.cleared_cards.add(pos)
            state.exp_points += 2
            cs.secured = True
            state.emit(f"Card {pos} cleared. +2 XP.")
            if "OBJ" in cs.tac_controls:
                state.exp_points += 10
                state.won = True
                state.finished = True
                state.emit(f"Primary Objective {pos} secured! +10 XP. MISSION SUCCESS.")
