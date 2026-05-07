"""Menu-driven player input. All prompts are numbered choices."""

from __future__ import annotations

from typing import Optional, Sequence

from ..game import state as gs
from ..game.state import GameState, Unit, SIDE_US, SIDE_GER
from ..game import commands as cmds
from ..game import los as losmod
from ..game import combat
from . import render


def _ask(prompt: str, options: Sequence[str], allow_skip: bool = True) -> Optional[int]:
    print(prompt)
    for i, opt in enumerate(options, 1):
        print(f"  {i}) {opt}")
    if allow_skip:
        print(f"  {len(options) + 1}) Cancel / skip")
    while True:
        s = input("> ").strip()
        if not s:
            continue
        try:
            n = int(s)
        except ValueError:
            print("Enter a number.")
            continue
        if 1 <= n <= len(options):
            return n - 1
        if allow_skip and n == len(options) + 1:
            return None
        print("Out of range.")


def _pick_unit(state: GameState, hq: Optional[Unit], action_label: str,
               filter_fn=None) -> Optional[Unit]:
    """Pick a friendly unit eligible for the action."""
    candidates = []
    for u in state.units:
        if u.side != SIDE_US:
            continue
        if u.status == gs.STATUS_CASUALTY:
            continue
        if filter_fn and not filter_fn(u):
            continue
        if hq is not None and hq.tier == "platoon" and u.platoon and u.platoon != hq.platoon and not u.is_hq:
            # PLT HQs control their own platoon's units
            if u.uid != hq.uid:
                continue
        candidates.append(u)
    if not candidates:
        print(f"No eligible units for {action_label}.")
        return None
    labels = []
    for u in candidates:
        loc = "Staging" if u.pos == "staging" else f"{u.pos}"
        st = []
        if u.pinned:
            st.append("Pinned")
        if u.exposed:
            st.append("Exposed")
        st_str = " " + ", ".join(st) if st else ""
        labels.append(f"{u.name} ({u.steps}st {u.exp}) @ {loc}{st_str}")
    idx = _ask(f"Pick unit for {action_label}:", labels)
    if idx is None:
        return None
    return candidates[idx]


def _pick_target_card(state: GameState, unit: Unit, action_label: str,
                      filter_fn=None) -> Optional[tuple]:
    if unit.pos == "staging":
        print(f"{unit.name} is in Staging — move onto the map first.")
        return None
    candidates = []
    for pos in state.cards:
        if pos == unit.pos:
            continue
        if filter_fn and not filter_fn(pos):
            continue
        candidates.append(pos)
    if not candidates:
        return None
    labels = [f"{pos} — {state.card(pos).terrain.name}" for pos in candidates]
    idx = _ask(f"Target card for {action_label}:", labels)
    if idx is None:
        return None
    return candidates[idx]


# ─── per-impulse menu ───


def impulse_menu(state: GameState, hq: Optional[Unit], available: int) -> int:
    """Drive an HQ's impulse. Return commands spent."""
    print("\n" + render.render_map(state))
    print()
    print(render.render_recent_log(state, 8))
    print()
    if hq is None:
        title = "GENERAL INITIATIVE IMPULSE"
        sub = "Spend on any unit. Cannot save."
    else:
        title = f"{hq.name} IMPULSE"
        sub = (
            f"Saved: {state.saved_commands.get(hq.uid, 0)} "
            f"| Cap/turn: {cmds.per_impulse_cap(state)} "
            f"| Save cap: {cmds.saved_command_cap(hq)}"
        )
    print(f"=== {title} — {available} commands available ===")
    print(sub)
    spent = 0
    while spent < available:
        remaining = available - spent
        opts = [
            f"Move unit to adjacent card (1 cmd)",
            f"Attempt Spot (1 cmd)",
            f"Attempt Concentrate Fire (1 cmd)",
            f"Attempt Grenade Attack (1 cmd)",
            f"Call for Fire (1 cmd; FO only)",
            f"Attempt to Seek Cover (1 cmd)",
            f"Attempt to Remove Pinned (1 cmd)",
            f"Cease Fire (1 cmd)",
            f"End impulse (save remaining: {remaining})",
        ]
        idx = _ask(f"Pick action ({remaining} commands left):", opts, allow_skip=False)
        if idx == 8:
            break
        if idx == 0:  # Move
            u = _pick_unit(state, hq, "Move", lambda x: not x.exposed and not x.is_lat())
            if u is None:
                continue
            if u.pos == "staging":
                # Pick a Row 1 destination
                positions = [(1, c) for c in range(1, state.map_cols + 1)]
                labels = [f"{p}" for p in positions]
                tidx = _ask("Enter map at:", labels)
                if tidx is None:
                    continue
                dest = positions[tidx]
            else:
                dest = _pick_target_card(state, u, "Move",
                                          lambda p: losmod.range_between(u.pos, p) == 1)
                if dest is None:
                    continue
            if cmds.move_to_adjacent(state, hq if hq else u, u, dest):
                spent += 1
        elif idx == 1:  # Spot
            u = _pick_unit(state, hq, "Spot", lambda x: x.pos != "staging")
            if u is None:
                continue
            target = _pick_target_card(state, u, "Spot")
            if target is None:
                continue
            if cmds.attempt_spot(state, hq if hq else u, u, target):
                spent += 1
            else:
                spent += 1  # attempt costs even on failure
        elif idx == 2:  # Concentrate Fire
            u = _pick_unit(state, hq, "Concentrate Fire",
                           lambda x: x.vof not in ("none", "") and x.pos != "staging")
            if u is None:
                continue
            target_pos = _pick_target_card(state, u, "Concentrate Fire")
            if target_pos is None:
                continue
            ger_units = [x for x in state.units_on(target_pos, SIDE_GER) if x.spotted]
            if not ger_units:
                print("No spotted enemies there.")
                continue
            tidx = _ask("Target unit:", [x.name for x in ger_units])
            if tidx is None:
                continue
            cmds.attempt_concentrate_fire(state, hq if hq else u, u, ger_units[tidx])
            spent += 1
        elif idx == 3:  # Grenade
            u = _pick_unit(state, hq, "Grenade Attack", lambda x: x.pos != "staging")
            if u is None:
                continue
            target = _pick_target_card(state, u, "Grenade Attack",
                                        lambda p: losmod.range_between(u.pos, p) <= 1)
            if target is None:
                continue
            cmds.attempt_grenade_attack(state, hq if hq else u, u, target)
            spent += 1
        elif idx == 4:  # Call for fire
            fos = [u for u in state.units
                   if u.is_fo and u.side == SIDE_US
                   and u.status != gs.STATUS_CASUALTY and u.pos != "staging"]
            if not fos:
                print("No FO on map. Move the Arty FO out of Staging first.")
                continue
            tidx = _ask("Pick FO:", [u.name for u in fos])
            if tidx is None:
                continue
            fo = fos[tidx]
            mtypes = [k for k, v in state.fire_missions.items() if v > 0]
            if not mtypes:
                print("No fire missions remaining.")
                continue
            mi = _ask("Mission type:", mtypes)
            if mi is None:
                continue
            target = _pick_target_card(state, fo, "Fire Mission")
            if target is None:
                continue
            cmds.call_for_fire(state, hq if hq else fo, fo, mtypes[mi], target)
            spent += 1
        elif idx == 5:  # Seek Cover
            u = _pick_unit(state, hq, "Seek Cover", lambda x: x.pos != "staging")
            if u is None:
                continue
            cmds.attempt_seek_cover(state, hq if hq else u, u)
            spent += 1
        elif idx == 6:  # Remove Pinned
            u = _pick_unit(state, hq, "Remove Pinned", lambda x: x.pinned)
            if u is None:
                continue
            cmds.attempt_remove_pinned(state, hq if hq else u, u)
            spent += 1
        elif idx == 7:  # Cease Fire
            u = _pick_unit(state, hq, "Cease Fire")
            if u is None:
                continue
            cmds.cease_fire(state, hq if hq else u, u)
            spent += 1
    return spent
