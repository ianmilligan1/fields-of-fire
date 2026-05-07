"""Smoke test: the game can run a turn cycle with a scripted player
that pushes units onto the map and triggers combat.

This is a high-coverage 'does it work' check. The detailed unit tests
live in the other test files.
"""

import random

from fields_of_fire.game import decks, sequence
from fields_of_fire.game.state import SIDE_US, SIDE_GER


def test_scripted_advance_runs_to_completion():
    """A scripted player advances onto the map and triggers PC contacts."""
    rng = random.Random(42)
    state = decks.setup_mission(rng)
    udata = decks.load_units()

    plan = {
        "1PLT": {"squads": ["1/1", "2/1"], "weapon": "1/W/1", "target_col": 1},
        "2PLT": {"squads": ["1/2", "2/2"], "weapon": "1/W/2", "target_col": 2},
        "3PLT": {"squads": ["1/3", "2/3"], "weapon": "1/W/3", "target_col": 3},
    }

    def scripted_impulse(s, hq, available):
        """Advance squads onto Row 1 then up. Crude but sufficient."""
        if hq is None or available <= 0:
            return 0
        if hq.uid not in plan:
            return 0
        spent = 0
        from fields_of_fire.game import commands as cmds
        squads_ids = plan[hq.uid]["squads"] + [plan[hq.uid]["weapon"], hq.uid]
        col = plan[hq.uid]["target_col"]
        for uid in squads_ids:
            if spent >= available:
                break
            u = s.find_unit(uid)
            if u is None or u.exposed or u.is_lat():
                continue
            if u.pos == "staging":
                if cmds.move_to_adjacent(s, hq, u, (1, col)):
                    spent += 1
            elif u.pos[0] < 3:
                # Move forward
                dest = (u.pos[0] + 1, u.pos[1])
                if dest in s.cards and not u.exposed:
                    if cmds.move_to_adjacent(s, hq, u, dest):
                        spent += 1
        return spent

    loop = sequence.GameLoop(state, scripted_impulse, udata["enemy_packages"])

    # Run up to max turns
    for _ in range(state.max_turns + 1):
        if state.finished:
            break
        loop.run_turn()

    # Sanity asserts
    assert state.turn > 1, "game must advance turns"
    # Some PC markers should have resolved
    placed_pcs = sum(1 for cs in state.cards.values() if cs.pc_marker is None)
    assert placed_pcs > 0, "Some PC markers should have been resolved"
    # We expect either victory or finished mission
    assert state.finished
