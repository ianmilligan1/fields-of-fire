"""ASCII map renderer."""

from __future__ import annotations

from ..game import state as gs
from ..game.state import GameState, Unit, SIDE_US, SIDE_GER


def _short_status(u: Unit) -> str:
    flags = []
    if u.pinned:
        flags.append("P")
    if u.exposed:
        flags.append("E")
    if u.activated:
        flags.append("*")
    if u.cover_marker:
        flags.append("C")
    return "".join(flags)


def _unit_label(u: Unit) -> str:
    name = u.name.replace(" Squad", "").replace(" Team", "T").replace(" HQ", "")
    name = name.replace("st PLT", "PLT")
    name = name[:8]
    flags = _short_status(u)
    if u.is_lat() or u.status == gs.STATUS_CASUALTY:
        return f"{name}({u.steps}){flags}"
    return f"{name}[{u.steps}]{flags}"


def render_map(state: GameState) -> str:
    cell_w = 18
    rows_out = []
    rows_out.append(
        f"=== TURN {state.turn}/{state.max_turns} — "
        f"{state.visibility.upper()} — ACTIVITY: {state.activity.upper()} ==="
    )
    rows_out.append("")
    # Column header
    header = "       " + "".join(f"  Col {c:<{cell_w-7}}" for c in range(1, state.map_cols + 1))
    rows_out.append(header)
    for r in range(state.map_rows, 0, -1):
        # Top border
        border = "       " + "+" + ("+".join(["-" * (cell_w - 1)] * state.map_cols)) + "+"
        rows_out.append(border)
        # Row label + each card line
        lines = ["", "", "", ""]
        for c in range(1, state.map_cols + 1):
            cs = state.cards.get((r, c))
            if cs is None:
                lines[0] += "|" + " " * (cell_w - 1)
                continue
            terrain = cs.terrain
            tac = " ".join(cs.tac_controls)
            l1 = f"{terrain.short} {terrain.cover_high:+d}/{terrain.cover_low:+d}"
            if cs.pc_marker:
                l1 += f" PC{cs.pc_marker}"
            if tac:
                l1 = f"[{tac}] " + l1
            l2 = ""
            if cs.vofs:
                v = min(cs.vofs, key=lambda x: x.value)
                l2 += f"VOF:{v.vof_type[:3]}({v.value:+d})"
            us_units = [u for u in state.units_on((r, c), SIDE_US)]
            ger_units = [u for u in state.units_on((r, c), SIDE_GER)]
            l3 = ",".join(_unit_label(u) for u in us_units[:2])
            l4_a = ",".join(_unit_label(u) for u in us_units[2:4])
            ger_label = ",".join(
                _unit_label(u) if u.spotted else f"?{_unit_label(u)}"
                for u in ger_units[:2]
            )
            if ger_label:
                l4_a = (l4_a + " " + ger_label).strip()
            for i, line in enumerate([l1, l2, l3, l4_a]):
                lines[i] += "|" + line[: cell_w - 1].ljust(cell_w - 1)
        for i, line in enumerate(lines):
            label = f"Row {r}  " if i == 0 else "       "
            rows_out.append(label + line + "|")
    rows_out.append("       " + "+" + ("+".join(["-" * (cell_w - 1)] * state.map_cols)) + "+")
    rows_out.append("       " + "═" * (cell_w * state.map_cols - 4) + " LINE OF DEPARTURE")
    # Staging area
    staging = [u for u in state.units if u.pos == "staging" and u.status != gs.STATUS_CASUALTY]
    if staging:
        names = ", ".join(u.name for u in staging[:8])
        rows_out.append(f"       [Staging] {names}{'...' if len(staging) > 8 else ''}")
    rows_out.append("")
    # Saved commands
    parts = []
    for hq_id in ["CO", "1PLT", "2PLT", "3PLT"]:
        v = state.saved_commands.get(hq_id, 0)
        parts.append(f"{hq_id}:{v}")
    rows_out.append("SAVED CMDS  " + " | ".join(parts))
    fm = state.fire_missions
    rows_out.append(
        f"FIRE MISSIONS  HE:{fm.get('HE',0)} | WP:{fm.get('WP',0)} | BN:{fm.get('BN',0)}"
    )
    rows_out.append(f"EXPERIENCE EARNED: {state.exp_points}")
    return "\n".join(rows_out)


def render_recent_log(state: GameState, n: int = 12) -> str:
    return "\n".join(state.log[-n:])
