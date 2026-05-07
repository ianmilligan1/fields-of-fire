"""Sequence-of-play tests — phase ordering, command modifiers, PC resolution."""

import random

from fields_of_fire.game import decks, sequence, commands as cmds, pc_resolution
from fields_of_fire.game import state as gs
from fields_of_fire.game.state import (
    SIDE_US, SIDE_GER, ACTIVITY_NO_CONTACT, ACTIVITY_CONTACT, ACTIVITY_ENGAGED,
    EXP_GREEN, EXP_LINE, EXP_VETERAN,
)


def _state():
    return decks.setup_mission(random.Random(0))


def test_command_modifier_no_contact_bonus():
    """No Contact: +1 to command draws (§4.1.2C)."""
    s = _state()
    co = s.find_unit("CO")
    co.pos = (1, 1)
    s.activity = ACTIVITY_NO_CONTACT
    assert cmds.command_draw_modifier(s, co) == 1


def test_command_modifier_pinned_and_green():
    s = _state()
    co = s.find_unit("CO")
    co.pos = (1, 1)
    co.exp = EXP_GREEN
    co.pinned = True
    s.activity = ACTIVITY_ENGAGED
    assert cmds.command_draw_modifier(s, co) == -2


def test_command_modifier_veteran_under_cover():
    s = _state()
    co = s.find_unit("CO")
    co.pos = (1, 1)
    co.exp = EXP_VETERAN
    co.cover_marker = "x"
    s.activity = ACTIVITY_ENGAGED
    # Vet +1, Cover +1 = +2
    assert cmds.command_draw_modifier(s, co) == 2


def test_saved_command_caps():
    s = _state()
    green_hq = s.find_unit("3PLT")
    green_hq.exp = EXP_GREEN
    line_hq = s.find_unit("1PLT")
    line_hq.exp = EXP_LINE
    vet_hq = s.find_unit("2PLT")
    vet_hq.exp = EXP_VETERAN
    assert cmds.saved_command_cap(green_hq) == 3
    assert cmds.saved_command_cap(line_hq) == 6
    assert cmds.saved_command_cap(vet_hq) == 9


def test_pc_resolution_at_no_contact_with_a():
    """An A-tier PC marker auto-contacts at No Contact level."""
    s = _state()
    sq = s.find_unit("1/1")
    sq.pos = (1, 1)
    s.cards[(1, 1)].pc_marker = "A"
    # Wipe other PCs to focus on this one
    for pos, cs in s.cards.items():
        if pos != (1, 1):
            cs.pc_marker = None
    udata = decks.load_units()
    pc_resolution.evaluate_potential_contacts(s, udata["enemy_packages"])
    # PC marker should be removed
    assert s.cards[(1, 1)].pc_marker is None


def test_activity_level_increases_after_vof():
    s = _state()
    sq = s.find_unit("1/1")
    sq.pos = (1, 1)
    from fields_of_fire.game.state import VOFMarker, VOF_VALUES
    s.cards[(1, 1)].vofs.append(VOFMarker(
        vof_type="S", value=VOF_VALUES["S"], origin=(1, 2)
    ))
    s.update_activity()
    assert s.activity in (ACTIVITY_CONTACT, ACTIVITY_ENGAGED)


def test_full_run_completes_with_seed():
    """End-to-end determinism: a fixed seed produces a finished game."""
    rng = random.Random(123)
    s = decks.setup_mission(rng)
    udata = decks.load_units()
    loop = sequence.GameLoop(s, lambda *a: 0, udata["enemy_packages"])
    for _ in range(s.max_turns + 1):
        if s.finished:
            break
        loop.run_turn()
    assert s.finished
