"""Generate the action_deck.json. Each card has all sections populated.

Field mapping (per rules 2.8):
  number: card 1..60
  activated_cmd: helmet number (1..6)
  initiative_cmd: star number (0..3)
  combat_resolution: dict ncm_str -> "HIT"|"PIN"|"MISS" for ncm in -4..+6
  hit_effect: {green: 'CF', line: 'PF', veteran: 'FF'}  (1-2 letters from C/F/L/P/A)
  icons: dict of bool flags for: contact, spotted, hq, cover, rally,
         crosshairs, grenade, infiltrate, burst, burst3, short, jam, hq_event
  at_modifier: -2..+2
  random_number: 1..9

Distribution is a thoughtful rough fit to the published deck — frequencies
informed by section 2.8 descriptions and Field Manual examples, not a
1:1 reproduction (the actual deck data is GMT IP). RULEBOOK AMBIGUITY:
exact card-by-card data is not in the rulebook, so this is a calibrated
synthesis.
"""

import json
import random
from pathlib import Path


def card_combat_row(seed_idx: int) -> dict:
    """Combat resolution row: each NCM -4..+6 maps to HIT, PIN, or MISS.
    The intuitive distribution: very negative NCM is mostly HIT, very
    positive mostly MISS, middle is PIN-band that varies card to card.
    Use a deterministic threshold per card so the column stays internally
    consistent (a card 'leans hit' or 'leans miss')."""
    rng = random.Random(7919 + seed_idx)
    # Each card has a "harshness" — where the HIT→PIN→MISS thresholds sit.
    pin_low = rng.randint(-3, 0)   # NCM <= pin_low: HIT
    miss_low = pin_low + rng.randint(2, 4)  # pin_low < NCM < miss_low: PIN
    out = {}
    for ncm in range(-4, 7):
        if ncm <= pin_low:
            out[str(ncm)] = "HIT"
        elif ncm < miss_low:
            out[str(ncm)] = "PIN"
        else:
            out[str(ncm)] = "MISS"
    return out


def card_hit_effect(seed_idx: int) -> dict:
    """Two-letter hit effect per experience column. Veteran is gentlest,
    Green is harshest. Letters: C=Casualty, P=Paralyzed, L=Litter,
    F=Fire team, A=Assault team."""
    rng = random.Random(13_001 + seed_idx)
    # Per-experience pools weighted toward gentleness/harshness.
    vet_pool = "AAAFFFLPP"   # mostly Assault/Fire — they hold together
    line_pool = "AFFFFLLPC"  # mix
    green_pool = "FFLLPPCCC"  # heavy casualties
    return {
        "veteran": rng.choice(vet_pool) + rng.choice(vet_pool),
        "line": rng.choice(line_pool) + rng.choice(line_pool),
        "green": rng.choice(green_pool) + rng.choice(green_pool),
    }


def card_icons(seed_idx: int) -> dict:
    """Action attempt icons — sparse, multiple may appear on one card.
    Probabilities tuned so attempts feel uncertain but not impossible."""
    rng = random.Random(2003 + seed_idx)
    return {
        "contact": rng.random() < 0.30,
        "spotted": rng.random() < 0.18,
        "cover": rng.random() < 0.30,
        "rally": rng.random() < 0.22,
        "crosshairs": rng.random() < 0.28,
        "grenade": rng.random() < 0.22,
        "infiltrate": rng.random() < 0.20,
        "burst": rng.random() < 0.30,
        "burst3": rng.random() < 0.10,
        "short": rng.random() < 0.06,
        "jam": rng.random() < 0.05,
        "hq_event": rng.random() < 0.10,
    }


def build_card(num: int) -> dict:
    rng = random.Random(num * 17 + 5)
    activated = rng.choices([1, 2, 3, 4, 5, 6], weights=[2, 4, 5, 5, 4, 2])[0]
    initiative = rng.choices([0, 1, 2, 3], weights=[3, 5, 4, 1])[0]
    return {
        "number": num,
        "activated_cmd": activated,
        "initiative_cmd": initiative,
        "combat_resolution": card_combat_row(num),
        "hit_effect": card_hit_effect(num),
        "icons": card_icons(num),
        "at_modifier": rng.choices([-2, -1, 0, 1, 2], weights=[1, 2, 4, 2, 1])[0],
        "random_number": rng.randint(1, 9),
    }


def main() -> None:
    cards = [build_card(i) for i in range(1, 61)]
    out = {
        "_comment": (
            "60-card synthesized Action Deck. Each card carries five layers "
            "of information per FOF 3rd Ed §2.8: activated/initiative command "
            "numbers, action attempt icons, combat resolution column, hit "
            "effect by experience, and random number. RULEBOOK AMBIGUITY: "
            "GMT does not publish per-card data; this distribution is a "
            "calibrated synthesis intended to feel like the published deck."
        ),
        "cards": cards,
    }
    path = Path(__file__).with_name("action_deck.json")
    path.write_text(json.dumps(out, indent=2))
    print(f"Wrote {len(cards)} cards to {path}")


if __name__ == "__main__":
    main()
