"""GameState — single source of truth for the game.

Coordinates: (row, col) where row 1 is the bottom (closest to friendly
Line of Departure) and row 3 is the top (objective). Columns are 1..4
left-to-right. The Staging Area is the abstract location 'staging' (units
there have not yet entered the map).

Implements §1-3 of the rulebook. See game/sequence.py for phase logic.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Iterable, Optional


# ──────────────────────────── enums / constants ──────────────────────────


# Activity levels per §8.1.
ACTIVITY_NO_CONTACT = "NoContact"
ACTIVITY_CONTACT = "Contact"
ACTIVITY_ENGAGED = "Engaged"
ACTIVITY_HEAVILY_ENGAGED = "HeavilyEngaged"

# Visibility (§9). MVP only uses Daylight.
VIS_DAYLIGHT = "Daylight"

# Status flags on a unit.
STATUS_GOOD = "GoodOrder"
STATUS_PINNED = "Pinned"
# LAT statuses — set when a step converts via Hit Effect.
LAT_FIRE = "FireTeam"
LAT_ASSAULT = "AssaultTeam"
LAT_LITTER = "LitterTeam"
LAT_PARALYZED = "ParalyzedTeam"
STATUS_CASUALTY = "Casualty"

EXP_GREEN = "green"
EXP_LINE = "line"
EXP_VETERAN = "veteran"

# VOF rating numerical values per §6.2.2.
VOF_VALUES = {
    "S": 0,
    "A": -1,
    "H": -3,
    "Pinned": +2,
    "G!": -3,   # Mission can override to -4 — Normandy uses -3 per 7.10.2.
    "S!": -3,   # Sniper VOF
    "Mines!": -3,
    "Incoming!": -5,  # HE per units.json
    "WP!": -3,
    "Booby!": -4,
}

# Side identifiers.
SIDE_US = "US"
SIDE_GER = "GER"


# ──────────────────────────── data classes ───────────────────────────────


@dataclass
class Unit:
    """One on-map (or staging) unit. Multi-step squads are a single Unit
    here; reductions break off LAT-typed Units via combat resolution."""

    uid: str                      # unique runtime id
    name: str                     # display name
    side: str                     # SIDE_US / SIDE_GER
    vof: str                      # 'S','A','H','G!','S!','none'
    range_: str                   # 'P','C','L','VL','none'
    exp: str                      # green/line/veteran
    steps: int                    # current steps (1..4)
    max_steps: int                # original steps
    pos: object = "staging"       # (row,col) or 'staging'
    status: str = STATUS_GOOD
    pinned: bool = False
    exposed: bool = False
    spotted: bool = True          # enemies may start unspotted
    is_hq: bool = False
    is_fo: bool = False
    is_pc_marker: bool = False
    fo_type: str = ""             # 'arty' / 'mtr'
    weapon_type: str = ""         # 'lmg', 'mortar', etc.
    tier: str = ""                # 'company','platoon','staff'
    platoon: str = ""             # '1','2','3' or ''
    cover_marker: Optional[str] = None  # cover marker id on this card
    activated: bool = False
    fire_mission_count: int = 0   # for enemy spotters
    ammo: Optional[int] = None
    activity_checked_this_turn: bool = False
    special: str = ""             # 'sniper','spotter','mines','booby_trap','no_contact'

    def vof_value(self) -> int:
        """Numeric VOF value when this unit fires."""
        if self.pinned:
            return VOF_VALUES["Pinned"]
        return VOF_VALUES.get(self.vof, 99)

    def is_lat(self) -> bool:
        return self.status in (LAT_FIRE, LAT_ASSAULT, LAT_LITTER, LAT_PARALYZED)

    def can_fire(self) -> bool:
        if self.status == STATUS_CASUALTY:
            return False
        if self.vof in ("none", ""):
            return False
        return True


@dataclass
class TerrainCard:
    name: str
    short: str
    cover_high: int
    cover_low: int
    cover_potential: int
    cover_draws: int
    elevation: int
    borders: str          # NESW: 'd' or 'w'
    cover_type: str       # e.g. '+1', '+2'

    @classmethod
    def from_dict(cls, d: dict) -> "TerrainCard":
        return cls(
            name=d["name"], short=d["short"],
            cover_high=d["cover_high"], cover_low=d["cover_low"],
            cover_potential=d["cover_potential"], cover_draws=d["cover_draws"],
            elevation=d["elevation"], borders=d["borders"],
            cover_type=d["cover_type"],
        )


@dataclass
class VOFMarker:
    """A VOF marker on a card. Per §6.2.1 we track who is firing (origin
    cards) so we can recompute when units move/are eliminated."""

    vof_type: str              # 'S','A','H','Pinned','G!','S!','Incoming!','WP!','Mines!'
    value: int                 # numeric value (best-of)
    origin: object = None      # (row,col) of firer, or 'offmap'
    target_unit: Optional[str] = None  # for unit-targeted VOF (Concentrated, Sniper)
    pending: bool = False      # for indirect fire missions
    short: bool = False        # short round


@dataclass
class PDFMarker:
    """A direction-of-fire marker; arrow from origin card to target card."""

    origin: tuple              # (row,col)
    target: tuple              # (row,col)


@dataclass
class CoverMarker:
    """A discovered cover marker on a card. Each represents a distinct area."""

    cover_id: str              # unique on the card
    value: int                 # +1, +2, etc.
    type_: str = "basic"


@dataclass
class CardState:
    terrain: TerrainCard
    vofs: list = field(default_factory=list)
    pdfs: list = field(default_factory=list)
    covers: list = field(default_factory=list)
    pc_marker: Optional[str] = None       # 'A','B','C', or None
    smoke: bool = False
    incoming: bool = False                # blocks LOS through
    crossfire: bool = False
    grenade_miss: bool = False
    concentrated_fire_targets: list = field(default_factory=list)
    tac_controls: list = field(default_factory=list)  # 'OBJ','AP','LoD','LoA','LB','RB'
    secured: bool = False                 # cleared & friendly-occupied


@dataclass
class GameState:
    """Single source of truth. All systems read/write here."""

    rng: random.Random
    map_rows: int = 3
    map_cols: int = 4
    cards: dict = field(default_factory=dict)   # (r,c) -> CardState
    units: list = field(default_factory=list)   # all Unit instances
    action_deck: list = field(default_factory=list)
    action_discard: list = field(default_factory=list)
    turn: int = 1
    max_turns: int = 10
    activity: str = ACTIVITY_NO_CONTACT
    visibility: str = VIS_DAYLIGHT
    saved_commands: dict = field(default_factory=dict)  # hq_uid -> int
    fire_missions: dict = field(default_factory=dict)   # type -> remaining
    log: list = field(default_factory=list)             # narrative event log
    exp_points: int = 0
    cleared_cards: set = field(default_factory=set)
    secured_cards: set = field(default_factory=set)
    won: bool = False
    finished: bool = False
    objective: tuple = (3, 2)
    attack_position: tuple = (2, 2)

    # ─── deck ops ───

    def draw_card(self) -> dict:
        """Draw one Action card; reshuffle discard if exhausted."""
        if not self.action_deck:
            self.action_deck = self.action_discard
            self.action_discard = []
            self.rng.shuffle(self.action_deck)
        c = self.action_deck.pop()
        self.action_discard.append(c)
        return c

    def draw_cards(self, n: int) -> list:
        return [self.draw_card() for _ in range(n)]

    # ─── card / map helpers ───

    def card(self, pos) -> Optional[CardState]:
        if pos == "staging":
            return None
        return self.cards.get(pos)

    def all_positions(self) -> Iterable[tuple]:
        return self.cards.keys()

    def units_on(self, pos, side: Optional[str] = None) -> list:
        out = []
        for u in self.units:
            if u.pos != pos:
                continue
            if u.status == STATUS_CASUALTY:
                continue
            if side is not None and u.side != side:
                continue
            out.append(u)
        return out

    def find_unit(self, uid: str) -> Optional[Unit]:
        for u in self.units:
            if u.uid == uid:
                return u
        return None

    # ─── narration ───

    def emit(self, msg: str) -> None:
        self.log.append(f"T{self.turn}: {msg}")

    # ─── activity level (§8.1) ───

    def update_activity(self) -> None:
        spotted_enemies = any(
            u.side == SIDE_GER and u.spotted and u.status != STATUS_CASUALTY
            and u.pos != "staging"
            for u in self.units
        )
        cards_with_vof = [
            pos for pos, c in self.cards.items() if c.vofs
        ]
        any_pdf_or_pending = any(
            c.vofs or c.pdfs for c in self.cards.values()
        )
        new = ACTIVITY_NO_CONTACT
        if cards_with_vof or spotted_enemies or any_pdf_or_pending:
            new = ACTIVITY_CONTACT
        # Engaged: 2+ occupied cards under VOF
        engaged_cards = [
            pos for pos in cards_with_vof
            if self.units_on(pos)
        ]
        if len(engaged_cards) >= 2:
            new = ACTIVITY_ENGAGED
        # Heavily engaged: 2+ engaged cards and at least one is jointly occupied
        heavy = False
        for pos in engaged_cards:
            us = self.units_on(pos, SIDE_US)
            ger = self.units_on(pos, SIDE_GER)
            if us and ger:
                heavy = True
                break
        if heavy and len(engaged_cards) >= 2:
            new = ACTIVITY_HEAVILY_ENGAGED
        if new != self.activity:
            self.emit(f"Activity Level → {new}")
            self.activity = new
