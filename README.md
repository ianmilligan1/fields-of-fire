# Fields of Fire — Text-Based Solitaire (3rd Edition Series Rules)

A Python terminal implementation of the GMT solitaire game **Fields of Fire**
(Ben Hull, 3rd Edition Series Rules, 2024). Captures the core decision loop:
issuing scarce Commands, drawing Action cards that drive combat, fire support,
and friction; reacting to Potential Contacts that materialize an enemy as you
push your company forward.

This is a **vibe-code** implementation — fidelity to the *decision space*, not
the published deck data (which is GMT IP). The Action Deck here is a 60-card
synthesis calibrated to feel right; the Terrain Deck and TO&E mirror Normandy
Mission 1.

## Run

```sh
python -m fields_of_fire           # interactive
python -m fields_of_fire --seed 7  # deterministic
python -m fields_of_fire --auto    # AI auto-play (saves all commands)
```

A turn-by-turn ASCII map appears with a menu of legal actions. Pick
numbered options.

## Tests

```sh
python -m pytest fields_of_fire/tests/ -v
```

21 tests cover NCM calculation, Hit Effects, LOS borders, smoke, command
modifiers, PC resolution, and full-game determinism.

## What's implemented (MVP scope)

| Rule section | Module | Status |
| --- | --- | --- |
| §1.2 Components, units, action card | `data/units.json`, `data/action_deck.json` | full |
| §2 Mission setup (Normandy 1, 4×3 face-up) | `game/decks.setup_mission` | full |
| §2.8 Action Card structure (5 sections) | `data/action_deck.json` | full |
| §3 Sequence of Play (8 phases) | `game/sequence.GameLoop` | full |
| §4 Commands & action menus | `game/commands.py`, `ui/prompts.py` | core actions |
| §4.1.2 Command-draw modifiers | `game/commands.command_draw_modifier` | full |
| §4.1.3 Saved-command caps | `game/commands.saved_command_cap` | full |
| §5 Movement, LOS, terrain | `game/los.py`, `game/commands.move_to_adjacent` | core (no infiltrate) |
| §5.2.2 Hill / elevation | `game/los.has_los` | partial |
| §5.4 Smoke / blocked LOS | `game/los.has_los` | full |
| §6.0 Basic Combat Principle (auto Open Fire) | `game/combat.open_fire_all` | full |
| §6.1.1 Open Fire priorities | `game/combat._pick_target` | core |
| §6.2 VOF placement | `game/combat.open_fire`, `game/state.VOFMarker` | full |
| §6.3 PDF markers | `game/state.PDFMarker` | full |
| §6.4 NCM, HIT/PIN/MISS, Hit Effects | `game/combat.compute_ncm`, `apply_hit_effect` | full |
| §6.5 Rally (Pinned, LATs) | `game/commands.attempt_remove_pinned` | partial |
| §7.10 Grenade Attacks | `game/commands.attempt_grenade_attack` | full |
| §7.16 Indirect Fire (Call for Fire, pending → active, Short) | `game/commands.call_for_fire` | full |
| §8 Enemy AI (Activity Hierarchy, Pinned/LAT, Snipers, Spotters) | `game/enemy_ai.py` | core |
| §8.2 PC markers, Activity Levels | `game/state.update_activity`, `game/pc_resolution` | full |
| §8.3 Enemy package generation | `game/pc_resolution`, `data/units.json` | full |
| §8.4 Package placement (distance, direction, max LOS) | `game/pc_resolution._place_at_distance` | core |

## What's stubbed / out of scope (per the original prompt)

- **Vehicles, AT combat, AT guns** (§10) — phase 3.6 is a no-op.
- **Helicopter / amphibious assault** (§11) — not modelled.
- **Urban combat** (§13) — not modelled.
- **Limited visibility / night** (§9) — game forced to Daylight.
- **Defensive missions / Combat Patrols** — Normandy Mission 1 only.
- **Reattempt** (§3.9) — game ends at turn 10 if objective unsecured.
- **Ammunition tracking** (§7.18) — assumed unlimited.
- **Runners, phone lines, full radio nets** (§4.3) — assumed CO TAC always works.
- **Mines & Booby Traps as full systems** — placed as one-shot VOFs.
- **Multi-step weapon-team breakdown into named Fire Teams** — generic LATs only.
- **Assault Teams / Convert Fire→Assault** — not in player menu (LATs created by combat are tagged but no upgrade path).
- **Crossfire detection (§6.2.4)** — placeholder flag, not auto-set.
- **Concentrate Platoon / Move Platoon as bundled actions** — handle one unit at a time.
- **Reconstitution** (§6.5.2) — not in player menu.
- **Pyrotechnics, Smoke grenades** (§4.4) — only WP fire missions provide smoke.
- **Out-of-Ammo behaviour** (§7.18.4) — not modelled.

## Files

```
fields_of_fire/
  __main__.py                  entry point
  data/
    action_deck.json           60-card synthesised deck
    build_action_deck.py       generator script
    terrain.json               9 Normandy terrain types
    units.json                 US TO&E + enemy packages + fire missions
  game/
    state.py                   GameState, Unit, CardState dataclasses
    decks.py                   loaders & mission setup
    sequence.py                §3 Sequence of Play orchestrator
    commands.py                §4 player action menus
    combat.py                  §6 NCM, Hit Effects, Open Fire
    pc_resolution.py           §8.2/8.3/8.4 PC resolution
    enemy_ai.py                §8.6 Activity Check Hierarchy
    los.py                     §5.2 LOS, range, elevation, smoke
  ui/
    render.py                  ASCII map renderer
    prompts.py                 numbered menu input
  tests/
    test_combat.py             NCM, Hit Effects, VOF stacking
    test_los.py                borders, smoke, range
    test_sequence.py           command modifiers, PC, full run
    test_smoke.py              scripted end-to-end advance
```

## Determinism

All randomness routes through `state.rng` (a `random.Random`). Pass `--seed`
for reproducible play. The test suite uses fixed seeds.

## Rule-interpretation notes

See [`RULES_INTERPRETATION.md`](RULES_INTERPRETATION.md) for every place we
made a judgement call — primarily around ambiguous/uncalibrated values
(PC Draws table, Command Draw modifiers under specific VOFs, Hit Effect
breakdown by experience).
