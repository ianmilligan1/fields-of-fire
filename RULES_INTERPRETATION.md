# Rules Interpretation Notes

Every place this implementation made a judgement call where the rulebook
either didn't specify a value, was ambiguous, or where I deliberately
simplified to keep MVP scope manageable. Section numbers refer to
*Fields of Fire 3rd Edition Series Rules* (GMT, 2024).

## Action Deck composition (§2.8)

GMT does not publish per-card data — the card-by-card frequencies of icons,
combat columns, and hit effects are physical card data. I synthesised a
60-card deck (`data/build_action_deck.py`) using calibrated probability
distributions:

- **Activated commands**: weighted 1–6, mode at 3.
- **Initiative commands**: weighted 0–3, mode at 1.
- **Action attempt icons**: each ~15–30% per card. Burst (~30%), Crosshairs
  (~28%), Cover (~30%), Contact (~30%), Rally (~22%), Grenade (~22%),
  Infiltrate (~20%). Short (~6%) and Jam (~5%) are rare.
- **Combat resolution column**: each card has its own internal threshold,
  so it "leans HIT" or "leans MISS" — driving the feel that some draws are
  brutal and some merciful.
- **Hit Effect**: weighted by experience pool. Veteran column favours
  Assault/Fire results; Green column favours Casualty/Paralyzed.

This isn't the published deck. It's a feel-aligned synthesis. The data
file is the only place to tune balance — no rule code is hardcoded.

## PC Draws table (§8.2.4)

The actual letter × Activity Level table is on Player Aid card #52, not in
the rulebook text. Calibrated values in `pc_resolution.PC_DRAWS`:

| | No Contact | Contact | Engaged | Heavily Engaged |
|---|---|---|---|---|
| **A** | Auto | Auto | 1 | 2 |
| **B** | 1 | 2 | 3 | 4 |
| **C** | 2 | 3 | 4 | 5 |

A is most severe (auto-contact under low activity), C is least.

## Command-draw VOF modifier scaling (§4.1.2 B)

Rule 4.1.2.B says S=–1, A=–2, H/Sniper/Grenade/Incoming/Air Strike=–3. The
implementation lumps "S or worse to –1, A to –2, H/special to –3" using a
crude mapping based on the *value* of the best VOF affecting the HQ:
`<= -3 → -3`, `<= -1 → -2`, `<= 0 → -1`. This is functionally equivalent
for Basic VOFs.

## Hit Effect breakdown (§6.4.3)

The full breakdown chart maps each (unit type × step number × hit letter)
to a specific named Fire Team counter. The Mission Books contain the
detailed charts. We use the simpler universal fallback: every step
becomes a generic LAT (Casualty / Paralyzed / Litter / Fire / Assault).
A future enhancement is to add named Fire Teams — the data structure
already supports `weapon_type` so the breakdown chart can read from it.

## Friendly Higher HQ Events (§3.1) and Enemy Higher HQ Events (§3.4.1)

The actual events are in the Mission Book. We use a 9-bucket synthesis
keyed off the drawn card's R# (random number):

- Friendly: 1–3 bonus HE; 4–6 bonus BN; 7–8 nothing; 9 lose a fire mission.
- Enemy: 1–3 extra PC marker on row 3; 4–6 enemies aggressively re-engage;
  7–8 nothing; 9 free Incoming! on row 1.

## Activity Check Hierarchy (§8.6.2)

The published Pinned/LAT and Offensive/Defensive tables cross-reference
specific R#s with specific actions. We approximate with a priority-based
descriptive logic in `enemy_ai.py`:

- **Pinned/LAT**: try to rally up the LAT chain (Paralyzed→Litter→Fire),
  rally Pinned via 2-card draw for Rally icon.
- **Good Order Defensive**: Seek Cover if under fire and no cover; Fall
  Back ~30% under Heavily Engaged; otherwise Concentrate Fire on biggest
  US target in LOS.
- **Snipers**: own behaviour per §8.8. Fall back if spotted.
- **Spotters**: own behaviour per §8.10. Call for fire on largest US
  card in LOS.

## Friendly auto-Open Fire on jointly occupied cards (§6.1.1)

Per the rule, friendly units do *not* automatically open fire on cards
where both sides are present (you have to issue the order). Implemented
in `combat._eligible_targets`: if the firer is friendly and the target
card is jointly occupied, it's filtered out.

## Movement: Exposed marker (§5.1.3)

Any move that isn't a successful Infiltrate marks the moving unit
Exposed. Once Exposed, the unit cannot move to another card in the same
turn (but can Move within Card / Seek Cover). Implemented as a flag on
`Unit.exposed`, cleared in Clean Up.

## "Card cleared" XP awards (§12.1)

The rule awards XP for clearing/securing cards. We implement a simple
rule: any card with US units and no enemies, that wasn't previously
cleared, gets +2 XP, and securing the Primary Objective is +10 XP and
ends the mission. This means a card with a "no contact" PC resolution
that is then occupied counts as cleared — that matches the rules text
(clearing = friendly-occupied, no enemies) and isn't gamey because PCs
that *don't* resolve still cost the player turns of movement.

## Cover & Concealment value choice (§5.2.3)

The rule picks the higher value if any fire crosses a dark border. We
implement this in `combat._fire_from_dark_border` for adjacent shots
only. Long/Very Long range fire that crosses multiple borders simplifies
to using `cover_low` since the LOS already had to pass through white
borders.

## Friendly command flow simplification (§3.3)

The full Activation Segment requires the CO HQ to spend a Command to
Activate each PLT HQ before that PLT can act. Our MVP auto-activates
the CO HQ and all PLT HQs every turn — players don't have to spend
Activate commands explicitly. This trades a layer of friction for a
simpler menu. RULEBOOK AMBIGUITY: chose simplification because the
Activate-then-spend chain is rarely a meaningful decision in solo play
(you almost always activate everyone).

## What we don't simulate but should be aware of

- **Reciprocal LOS** (§5.2.1): spotting and combat are checked from each
  side independently; the LOS function is symmetric, so this naturally
  works (US can see X iff X can see US).
- **Multi-step LATs**: a 4-step squad taking a "PA" hit creates one
  Paralyzed and one Assault Team. Both LATs are real, separately tracked
  Units in `state.units`. The original squad's `steps` decreases.
- **VOF stacking on jointly occupied cards** (§6.2.1b): we place all
  VOFs in a single list per card; the "best of" logic in
  `_best_vof_affecting` filters by `target_unit` for unit-specific VOFs
  but otherwise treats them as card-wide. Refinement opportunity.
