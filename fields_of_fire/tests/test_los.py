"""LOS tests — borders, range, smoke, elevation."""

import random

from fields_of_fire.game import decks, los
from fields_of_fire.game import state as gs


def _state():
    return decks.setup_mission(random.Random(0))


def test_adjacent_always_in_los():
    s = _state()
    # Force all-dark borders
    for cs in s.cards.values():
        cs.terrain.borders = "dddd"
    assert los.has_los(s, (1, 1), (1, 2))
    assert los.has_los(s, (1, 1), (2, 1))
    assert los.has_los(s, (1, 1), (2, 2))


def test_dark_border_blocks_long_range():
    s = _state()
    # Make (1,1)→(1,3) cross dark borders on intervening (1,2)
    s.cards[(1, 1)].terrain.borders = "dddd"
    s.cards[(1, 2)].terrain.borders = "dddd"
    s.cards[(1, 3)].terrain.borders = "dddd"
    s.cards[(1, 1)].terrain.elevation = 0
    s.cards[(1, 2)].terrain.elevation = 0
    s.cards[(1, 3)].terrain.elevation = 0
    assert not los.has_los(s, (1, 1), (1, 3))


def test_white_border_passes_long_range():
    s = _state()
    s.cards[(1, 1)].terrain.borders = "wwww"
    s.cards[(1, 2)].terrain.borders = "wwww"
    s.cards[(1, 3)].terrain.borders = "wwww"
    assert los.has_los(s, (1, 1), (1, 3))


def test_smoke_blocks_through():
    s = _state()
    for cs in s.cards.values():
        cs.terrain.borders = "wwww"
    s.cards[(1, 2)].smoke = True
    # LOS into (1,2) is OK (one-way)
    assert los.has_los(s, (1, 1), (1, 2))
    # LOS through (1,2) to (1,3) is blocked
    assert not los.has_los(s, (1, 1), (1, 3))


def test_range_label_matches_distance():
    assert los.range_label(0) == "P"
    assert los.range_label(1) == "C"
    assert los.range_label(2) == "L"
    assert los.range_label(3) == "VL"


def test_in_weapon_range():
    assert los.in_weapon_range("C", 1)
    assert not los.in_weapon_range("C", 2)
    assert los.in_weapon_range("VL", 3)
    assert not los.in_weapon_range("VL", 4)


def test_max_range_three():
    s = _state()
    # Distance > 3 should fail even on white borders
    for cs in s.cards.values():
        cs.terrain.borders = "wwww"
    # No card at distance 4 in 4×3 map from (1,1) anyway
    # but verify range_between handles diagonal
    assert los.range_between((1, 1), (3, 3)) == 2
    assert los.range_between((1, 1), (1, 4)) == 3
    # Off-ray points return -1
    assert los.range_between((1, 1), (3, 4)) == -1
