"""Sequence of Play orchestrator — §3.0.

Strict ordering, one phase/segment/impulse at a time. The player only
gets to make decisions during the Friendly Command Phase impulses;
every other phase is automatic.
"""

from __future__ import annotations

from typing import Callable

from . import state as gs
from . import combat, pc_resolution, enemy_ai, decks, commands as cmds
from .state import (
    GameState, Unit, SIDE_US, SIDE_GER, ACTIVITY_NO_CONTACT,
    ACTIVITY_CONTACT, ACTIVITY_ENGAGED, ACTIVITY_HEAVILY_ENGAGED,
)


PhaseUI = Callable[[GameState, Unit, int], int]
"""A callback signature: (state, hq, available_commands) → commands_spent.
The UI uses this to drive interactive impulses; tests pass a no-op."""


class GameLoop:
    def __init__(self, state: GameState, ui_impulse: PhaseUI, packages: dict):
        self.state = state
        self.ui_impulse = ui_impulse  # called for each Friendly impulse
        self.packages = packages       # enemy_packages dict

    # ─── Phase 3.1: Friendly Higher HQ Event Phase ───

    def phase_friendly_hq_event(self) -> None:
        if self.state.turn < 2:
            return
        c = self.state.draw_card()
        if c["icons"].get("hq_event"):
            evt = self.state.draw_card()
            r = evt["random_number"]
            self._friendly_hq_event(r)

    def _friendly_hq_event(self, r: int) -> None:
        # Simplified Friendly Higher HQ Events table (RULEBOOK AMBIGUITY:
        # actual table is in the Mission Book). MVP: 1-3 = bonus mission,
        # 4-6 = Battalion fire mission boost, 7-8 = nothing, 9 = adverse.
        if r <= 3:
            self.state.fire_missions["HE"] = self.state.fire_missions.get("HE", 0) + 1
            self.state.emit("Friendly HQ Event: extra HE fire mission!")
        elif r <= 6:
            self.state.fire_missions["BN"] = self.state.fire_missions.get("BN", 0) + 1
            self.state.emit("Friendly HQ Event: extra Battalion fire mission!")
        elif r <= 8:
            self.state.emit("Friendly HQ Event: no effect.")
        else:
            # Lose a fire mission
            for k in ["HE", "WP", "BN"]:
                if self.state.fire_missions.get(k, 0) > 0:
                    self.state.fire_missions[k] -= 1
                    self.state.emit(f"Friendly HQ Event: 1 {k} mission lost.")
                    break

    # ─── Phase 3.4: Enemy Activity Phase (Offensive) ───

    def phase_enemy_activity(self) -> None:
        # 3.4.1 Enemy Higher HQ Event Segment (Turn 2+)
        if self.state.turn >= 2:
            c = self.state.draw_card()
            if c["icons"].get("hq_event"):
                evt = self.state.draw_card()
                self._enemy_hq_event(evt["random_number"])
        # 3.4.2 Activity Check
        enemy_ai.enemy_activity_check(self.state)

    def _enemy_hq_event(self, r: int) -> None:
        if r <= 3:
            # Place an extra PC marker on a random row-3 card
            for c in range(1, self.state.map_cols + 1):
                cs = self.state.card((3, c))
                if cs and not cs.pc_marker:
                    cs.pc_marker = "B"
                    self.state.emit(f"Enemy HQ Event: PC B placed on (3,{c}).")
                    return
        elif r <= 6:
            # Boost enemy fire — re-trigger open fire for all enemies
            combat.open_fire_all(self.state)
            self.state.emit("Enemy HQ Event: enemies aggressively engage.")
        elif r <= 8:
            self.state.emit("Enemy HQ Event: no effect.")
        else:
            # Counterattack — enemy spotter calls a free fire mission on row 1
            for c in range(1, self.state.map_cols + 1):
                cs = self.state.card((1, c))
                if cs and self.state.units_on((1, c), SIDE_US):
                    from .state import VOFMarker, VOF_VALUES
                    cs.vofs.append(VOFMarker(
                        vof_type="Incoming!", value=-3, origin="offmap"
                    ))
                    self.state.emit(f"Enemy HQ Event: Incoming! on (1,{c})!")
                    return

    # ─── Phase 3.3: Friendly Command Phase ───

    def phase_friendly_command(self) -> None:
        s = self.state
        # 3.3.1a BN HQ Impulse
        # MVP: BN HQ off-map; Activate CO HQ automatically.
        co_hq = s.find_unit("CO")
        if co_hq is None:
            return
        co_hq.activated = True
        # 3.3.1b CO HQ Impulse
        c = s.draw_card()
        base = c["activated_cmd"]
        mod = cmds.command_draw_modifier(s, co_hq)
        cmd_pool = max(1, base + mod)
        saved = s.saved_commands.get("CO", 0)
        total = min(cmds.per_impulse_cap(s), cmd_pool + saved)
        spent = self.ui_impulse(s, co_hq, total)
        leftover = total - spent
        cap = cmds.saved_command_cap(co_hq)
        s.saved_commands["CO"] = min(cap, leftover)

        # 3.3.1c PLT HQ / CO Staff Impulses (if Activated by CO HQ in player's spending)
        # MVP: assume CO activates 1PLT, 2PLT, 3PLT each impulse if available.
        # Cleaner: have the CO impulse menu do this; for MVP, automatic activation.
        for plt in ["1PLT", "2PLT", "3PLT"]:
            hq = s.find_unit(plt)
            if hq is None or hq.status == gs.STATUS_CASUALTY:
                continue
            hq.activated = True
            c = s.draw_card()
            base = c["activated_cmd"]
            mod = cmds.command_draw_modifier(s, hq)
            cmd_pool = max(1, base + mod)
            saved = s.saved_commands.get(plt, 0)
            total = min(cmds.per_impulse_cap(s), cmd_pool + saved)
            spent = self.ui_impulse(s, hq, total)
            leftover = total - spent
            cap = cmds.saved_command_cap(hq)
            s.saved_commands[plt] = min(cap, leftover)

        # 3.3.2d General Initiative Impulse
        c = s.draw_card()
        gi = c["initiative_cmd"]
        if gi > 0:
            # Show as a generic "any unit" impulse
            spent = self.ui_impulse(s, None, gi)
            # General Initiative cannot be saved

    # ─── Phase 3.5: Mutual Capture & Retreat (skipped for MVP) ───
    def phase_capture_retreat(self) -> None:
        pass

    # ─── Phase 3.6: AT / Vehicle (skipped for MVP) ───
    def phase_at_vehicle(self) -> None:
        pass

    # ─── Phase 3.7: Mutual Combat ───

    def phase_mutual_combat(self) -> None:
        # 3.7.1 Fire Mission Update
        for cs in self.state.cards.values():
            for v in cs.vofs:
                if v.pending:
                    v.pending = False
                    self.state.emit("Pending fire mission flips active.")
        self.state.update_activity()
        # 3.7.2 Potential Contact Evaluation
        pc_resolution.evaluate_potential_contacts(self.state, self.packages)
        # 3.7.3 Pinned Recovery
        combat.pinned_recovery(self.state)
        # 3.7.4 Combat Effects
        combat.resolve_combat_effects(self.state)

    # ─── Phase 3.8: Clean Up ───

    def phase_cleanup(self) -> None:
        combat.clean_up(self.state)
        # Remove existing Incoming! markers (§3.7.1 sets up next turn)
        for cs in self.state.cards.values():
            cs.vofs = [v for v in cs.vofs if v.vof_type != "Incoming!"]
        # Re-evaluate Open Fire after smoke removal
        combat.open_fire_all(self.state)
        self.state.update_activity()

    # ─── Full turn driver ───

    def run_turn(self) -> None:
        self.state.emit(f"════════ TURN {self.state.turn} ════════")
        self.phase_friendly_hq_event()
        self.phase_enemy_activity()
        self.phase_friendly_command()
        self.phase_capture_retreat()
        self.phase_at_vehicle()
        self.phase_mutual_combat()
        self.phase_cleanup()
        self.state.turn += 1
        if self.state.finished:
            return
        if self.state.turn > self.state.max_turns:
            self.state.finished = True
            self.state.emit("Final turn complete — mission ends.")
