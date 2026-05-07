"""Enemy AI per §8.6.

For Offensive missions (us attacking, enemy defending) the enemy
priorities are roughly:

  Pinned/LAT: try to rally / fall back / convert → eventually retreat.
  Good Order Defensive:
    1. If under VOF: Seek Cover (if cover available) or Fall Back.
    2. If has spotted target in LOS: Concentrate Fire on biggest target.
    3. If has unspotted area where US is moving: Attempt Spot.
    4. Otherwise: hold position, ensure firing on best target.

This is a simplified Activity Check Hierarchy. RULEBOOK AMBIGUITY:
the actual table is on Player Aid card with cross-referenced random
numbers; we approximate using the descriptive priorities given in §8.6.
"""

from __future__ import annotations

from typing import Optional

from . import state as gs
from .state import (
    GameState, Unit, VOFMarker, PDFMarker,
    SIDE_GER, SIDE_US, VOF_VALUES,
    LAT_FIRE, LAT_ASSAULT, LAT_LITTER, LAT_PARALYZED,
    STATUS_GOOD, STATUS_PINNED, STATUS_CASUALTY,
)
from .los import has_los, range_between, in_weapon_range, cards_in_los
from . import combat


def _enemy_under_vof(state: GameState, u: Unit) -> bool:
    cs = state.card(u.pos)
    if not cs:
        return False
    return any(v.origin and v.origin != u.pos for v in cs.vofs)


def _seek_cover(state: GameState, u: Unit) -> bool:
    cs = state.card(u.pos)
    if not cs:
        return False
    if u.cover_marker:
        return False
    if cs.terrain.cover_potential <= len(cs.covers):
        return False
    draws = cs.terrain.cover_draws
    found = False
    for _ in range(draws):
        c = state.draw_card()
        if c["icons"].get("cover"):
            found = True
            break
    if found:
        marker_id = f"cover_{u.pos[0]}_{u.pos[1]}_{len(cs.covers)+1}"
        from .state import CoverMarker
        cm = CoverMarker(cover_id=marker_id, value=1, type_="basic")
        cs.covers.append(cm)
        u.cover_marker = marker_id
        u.exposed = True
        state.emit(f"{u.name} finds cover at {u.pos} (+1).")
        return True
    return False


def _fall_back(state: GameState, u: Unit) -> bool:
    """Fall back toward the top of the map (§8.6.3)."""
    if u.pos == "staging":
        return False
    r, c = u.pos
    candidates = []
    for new_pos in [(r + 1, c), (r + 1, c - 1), (r + 1, c + 1)]:
        if new_pos in state.cards:
            candidates.append(new_pos)
    if not candidates:
        # Off the top — remove from play
        state.emit(f"{u.name} falls off-map.")
        u.status = STATUS_CASUALTY
        return True
    candidates.sort(key=lambda p: -state.card(p).terrain.cover_high)
    new_pos = candidates[0]
    # Clear PDFs from origin
    src = state.card(u.pos)
    src.pdfs = [pdf for pdf in src.pdfs if pdf.origin != u.pos]
    u.pos = new_pos
    u.exposed = True
    state.emit(f"{u.name} falls back to {new_pos}.")
    return True


def _concentrate_fire(state: GameState, u: Unit) -> bool:
    """Approximate: attempt to fire/concentrate on a US target in LOS."""
    if not u.can_fire():
        return False
    targets = []
    for pos in cards_in_los(state, u.pos):
        d = range_between(u.pos, pos)
        if not in_weapon_range(u.range_, d):
            continue
        us = state.units_on(pos, SIDE_US)
        if us:
            targets.append((pos, sum(x.steps for x in us)))
    if not targets:
        return False
    targets.sort(key=lambda t: -t[1])
    target_pos = targets[0][0]
    # Place / move VOF + PDF if not already firing there
    src = state.card(u.pos)
    already = any(p.origin == u.pos and p.target == target_pos for p in src.pdfs)
    if already:
        # Try Concentrated Fire (1 card draw, look for crosshairs)
        c = state.draw_card()
        if c["icons"].get("crosshairs"):
            tcs = state.card(target_pos)
            us_units = state.units_on(target_pos, SIDE_US)
            if us_units:
                # Apply Concentrated Fire on a random unit
                victim = state.rng.choice(us_units)
                tcs.concentrated_fire_targets.append(victim.uid)
                state.emit(f"{u.name} concentrates fire on {victim.name}.")
                return True
    else:
        # Open Fire
        marker = VOFMarker(
            vof_type=u.vof if not u.pinned else "Pinned",
            value=u.vof_value(), origin=u.pos,
        )
        state.card(target_pos).vofs.append(marker)
        if target_pos != u.pos:
            src.pdfs.append(PDFMarker(origin=u.pos, target=target_pos))
        state.emit(f"{u.name} opens fire on {target_pos}.")
        state.update_activity()
        return True
    return False


def _act_pinned_or_lat(state: GameState, u: Unit) -> None:
    """Pinned/LAT: rally toward better state; LATs try to escape."""
    if u.pinned:
        # Attempt to remove pinned: 2-card draw for Rally icon
        cs = state.card(u.pos)
        auto = (not cs.vofs)
        if auto:
            u.pinned = False
            state.emit(f"{u.name} unpins (no VOF).")
            return
        cards = state.draw_cards(2)
        if any(c["icons"].get("rally") for c in cards):
            u.pinned = False
            state.emit(f"{u.name} rallies and unpins.")
        return
    # Litter team: try to convert up
    if u.status == LAT_LITTER:
        cs = state.card(u.pos)
        auto = not cs.vofs
        success = auto or any(c["icons"].get("rally") for c in state.draw_cards(2))
        if success:
            u.status = LAT_FIRE
            u.vof = "S"
            u.range_ = "C"
            state.emit(f"{u.name} converts Litter → Fire Team.")
        return
    if u.status == LAT_PARALYZED:
        cs = state.card(u.pos)
        auto = not cs.vofs
        success = auto or any(c["icons"].get("rally") for c in state.draw_cards(2))
        if success:
            u.status = LAT_LITTER
            state.emit(f"{u.name} converts Paralyzed → Litter.")
        return


def _act_good_order(state: GameState, u: Unit) -> None:
    """Defensive Activity hierarchy: try Seek Cover first if under fire,
    then Concentrate Fire on US, otherwise hold."""
    if _enemy_under_vof(state, u):
        if _seek_cover(state, u):
            return
        # If badly hurt or in heavy fire, fall back
        if state.activity == gs.ACTIVITY_HEAVILY_ENGAGED and state.rng.random() < 0.3:
            if _fall_back(state, u):
                return
    # Snipers: §8.8 — fire on highest priority, fall back if spotted
    if u.special == "ger_sniper":
        if u.spotted:
            _fall_back(state, u)
            return
        _concentrate_fire(state, u)
        return
    # Spotters: §8.10 — call for fire if missions remain
    if u.is_fo and u.fire_mission_count > 0:
        targets = []
        for pos in cards_in_los(state, u.pos):
            us = state.units_on(pos, SIDE_US)
            if us:
                targets.append((pos, sum(x.steps for x in us)))
        if targets:
            targets.sort(key=lambda t: -t[1])
            target_pos = targets[0][0]
            tcs = state.card(target_pos)
            tcs.vofs.append(VOFMarker(
                vof_type="Incoming!", value=-3, origin="offmap"
            ))
            u.fire_mission_count -= 1
            state.emit(f"{u.name} calls Incoming! on {target_pos} (missions left: {u.fire_mission_count}).")
            return
    # Default: open / continue fire
    _concentrate_fire(state, u)


def enemy_activity_check(state: GameState) -> None:
    """§3.4.2: cease fire on emptied targets, then activity-check each
    enemy unit in random card order, Pinned/LAT first, Good Order, then
    Leaders."""
    state.emit("─── Enemy Activity Check ───")

    # Cease fire on cards with no valid targets
    for pos, cs in state.cards.items():
        for pdf in list(cs.pdfs):
            tcs = state.card(pdf.target)
            if not tcs:
                continue
            if not state.units_on(pdf.target, SIDE_US):
                # No valid US targets → remove that VOF/PDF (cease fire)
                tcs.vofs = [v for v in tcs.vofs if v.origin != pdf.origin]
                cs.pdfs.remove(pdf)
                # Then re-open fire elsewhere (Basic Combat Principle)
    combat.open_fire_all(state)

    # Random card order
    enemy_cards = [pos for pos in state.cards if state.units_on(pos, SIDE_GER)]
    state.rng.shuffle(enemy_cards)
    for pos in enemy_cards:
        for u in state.units_on(pos, SIDE_GER):
            if u.activity_checked_this_turn:
                continue
            u.activity_checked_this_turn = True
            if u.is_lat() or u.pinned:
                _act_pinned_or_lat(state, u)
            else:
                _act_good_order(state, u)

    state.update_activity()
