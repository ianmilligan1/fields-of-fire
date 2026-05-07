"""Entry point: `python -m fields_of_fire`."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from .game import decks
from .game.sequence import GameLoop
from .ui import render
from .ui.prompts import impulse_menu


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fields of Fire — solitaire (text-based)")
    p.add_argument("--seed", type=int, default=None,
                   help="RNG seed for deterministic play")
    p.add_argument("--auto", action="store_true",
                   help="Auto-play (no prompts) — useful for smoke testing")
    args = p.parse_args(argv)

    rng = random.Random(args.seed)
    state = decks.setup_mission(rng)

    # Load enemy packages
    udata = decks.load_units()
    packages = udata["enemy_packages"]

    # UI callback
    if args.auto:
        ui_cb = lambda s, hq, n: 0  # spend nothing
    else:
        ui_cb = impulse_menu

    loop = GameLoop(state, ui_cb, packages)

    print(render.render_map(state))
    print()
    print(f"Mission: Normandy Offensive — secure the Primary Objective at {state.objective}")
    print(f"You command a US Rifle Company. {state.max_turns} turns.")
    print(f"Turn 1 begins.\n")

    while not state.finished:
        loop.run_turn()

    print()
    print("════════ MISSION END ════════")
    print(render.render_map(state))
    print()
    print("== FINAL LOG ==")
    print(render.render_recent_log(state, 30))
    print()
    if state.won:
        print(f"VICTORY — {state.exp_points} XP earned.")
    else:
        print(f"Mission ended without securing objective. {state.exp_points} XP.")
    return 0 if state.won else 1


if __name__ == "__main__":
    sys.exit(main())
