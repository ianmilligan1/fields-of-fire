"""Combat tests — NCM calculation, Hit Effects, LAT creation, VOF stacking."""

import random

import pytest

from fields_of_fire.game import combat, decks
from fields_of_fire.game import state as gs
from fields_of_fire.game.state import (
    Unit, VOFMarker, CoverMarker,
    SIDE_US, SIDE_GER, VOF_VALUES,
    LAT_FIRE, LAT_LITTER, LAT_PARALYZED, STATUS_CASUALTY,
    EXP_GREEN, EXP_LINE, EXP_VETERAN,
)


def _state():
    rng = random.Random(0)
    return decks.setup_mission(rng)


def test_ncm_basic_open_field_no_cover():
    """1/1 squad in Open Field hit by Heavy Weapons VOF: H=-3 + 0 cover = -3."""
    s = _state()
    sq = s.find_unit("1/1")
    sq.pos = (1, 1)
    # Force the card to Open terrain by mutating
    s.cards[(1, 1)].terrain.cover_high = 0
    s.cards[(1, 1)].terrain.cover_low = 0
    s.cards[(1, 1)].vofs.append(VOFMarker(
        vof_type="H", value=VOF_VALUES["H"], origin=(1, 2)
    ))
    s.cards[(1, 1)].terrain.borders = "wwww"
    ncm = combat.compute_ncm(s, sq)
    assert ncm == -3, f"expected -3, got {ncm}"


def test_ncm_pinned_modifier_and_cover_clamped():
    """Pinned defender: +1 modifier; cover marker +1; clamped to [-4, +6]."""
    s = _state()
    sq = s.find_unit("1/1")
    sq.pos = (1, 1)
    sq.pinned = True
    cm = CoverMarker(cover_id="x", value=1)
    s.cards[(1, 1)].covers.append(cm)
    sq.cover_marker = "x"
    s.cards[(1, 1)].terrain.cover_high = 1
    s.cards[(1, 1)].terrain.cover_low = 1
    s.cards[(1, 1)].terrain.borders = "wwww"
    s.cards[(1, 1)].vofs.append(VOFMarker(
        vof_type="S", value=VOF_VALUES["S"], origin=(1, 2)
    ))
    ncm = combat.compute_ncm(s, sq)
    # S(0) + cover(1) + pinned(+1) + cover_marker(+1) = +3
    assert ncm == 3


def test_ncm_clamp_high():
    """Even with massive defensive bonuses, NCM caps at +6."""
    s = _state()
    sq = s.find_unit("1/1")
    sq.pos = (1, 1)
    s.cards[(1, 1)].terrain.cover_high = 10
    s.cards[(1, 1)].terrain.cover_low = 10
    s.cards[(1, 1)].terrain.borders = "wwww"
    s.cards[(1, 1)].vofs.append(VOFMarker(
        vof_type="S", value=VOF_VALUES["S"], origin=(1, 2)
    ))
    ncm = combat.compute_ncm(s, sq)
    assert ncm == 6


def test_apply_hit_effect_cf_on_3step_line():
    """CF on a 3-step Line squad: step1→C, step2→F, last step is 1-step squad."""
    s = _state()
    sq = s.find_unit("1/1")
    sq.steps = 3
    sq.exp = EXP_LINE
    sq.pos = (1, 1)
    new = combat.apply_hit_effect(s, sq, "CF")
    assert sq.steps == 1
    assert sq.pinned is True
    casualties = [u for u in new if u.status == STATUS_CASUALTY]
    fire_teams = [u for u in new if u.status == LAT_FIRE]
    assert len(casualties) == 1
    assert len(fire_teams) == 1


def test_apply_hit_effect_p_on_one_step_team():
    """P on a 1-step team: converts to Paralyzed Team. Original step removed."""
    s = _state()
    lmg = s.find_unit("1/W/1")
    lmg.steps = 1
    lmg.pos = (1, 1)
    new = combat.apply_hit_effect(s, lmg, "P")
    assert lmg.steps == 0
    assert any(u.status == LAT_PARALYZED for u in new)


def test_best_vof_chosen():
    """When multiple VOFs hit the same card, the lowest (best) is used."""
    s = _state()
    sq = s.find_unit("1/1")
    sq.pos = (1, 1)
    s.cards[(1, 1)].terrain.cover_high = 0
    s.cards[(1, 1)].terrain.cover_low = 0
    s.cards[(1, 1)].terrain.borders = "wwww"
    s.cards[(1, 1)].vofs.append(VOFMarker(vof_type="S", value=0, origin=(1, 2)))
    s.cards[(1, 1)].vofs.append(VOFMarker(vof_type="A", value=-1, origin=(1, 3)))
    s.cards[(1, 1)].vofs.append(VOFMarker(vof_type="H", value=-3, origin=(2, 1)))
    ncm = combat.compute_ncm(s, sq)
    assert ncm == -3
