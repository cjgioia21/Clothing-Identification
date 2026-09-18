"""Download card data from the TCGdex API into a local card pool.

    python tools/fetch_pool.py                 # refresh pokedeck/data/cardpool.json.gz
    python tools/fetch_pool.py --sets sv08 me01

Only the fields the simulator reads are kept: HP, types, stage, retreat,
weakness, attacks, ability and Trainer text.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = "https://api.tcgdex.net/v2/en"
OUT = Path(__file__).resolve().parents[1] / "pokedeck" / "data" / "cardpool.json.gz"
SERIES = ["sv", "me"]
KEEP = (
    "id", "name", "category", "hp", "types", "stage", "evolveFrom", "retreat",
    "weaknesses", "resistances", "abilities", "attacks", "suffix", "trainerType",
    "effect", "energyType", "regulationMark", "rarity",
)


def get(path: str) -> dict | list:
    with urllib.request.urlopen(f"{API}{path}", timeout=60) as response:
        return json.load(response)


def set_ids(series: list[str]) -> list[str]:
    ids = []
    for name in series:
        ids.extend(s["id"] for s in get(f"/series/{name}")["sets"])
    return ids


def card_ids(set_id: str) -> list[str]:
    try:
        return [c["id"] for c in get(f"/sets/{set_id}").get("cards", [])]
    except Exception as exc:  # pragma: no cover - network shape varies
        print(f"  ! {set_id}: {exc}", file=sys.stderr)
        return []


def fetch_card(card_id: str) -> dict | None:
    for _ in range(3):
        try:
            raw = get(f"/cards/{card_id}")
            card = {k: raw[k] for k in KEEP if k in raw}
            card["set"] = raw.get("set", {}).get("id")
            card["setName"] = raw.get("set", {}).get("name")
            card["localId"] = raw.get("localId")
            return card
        except Exception:
            continue
    print(f"  ! failed {card_id}", file=sys.stderr)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sets", nargs="*", help="set ids (default: every SV and ME set)")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    sets = args.sets or set_ids(SERIES)
    print(f"{len(sets)} sets", file=sys.stderr)

    ids: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for set_id, found in zip(sets, pool.map(card_ids, sets)):
            print(f"  {set_id}: {len(found)} cards", file=sys.stderr)
            ids.extend(found)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        cards = [c for c in pool.map(fetch_card, ids) if c]

    payload = {"source": "https://tcgdex.dev", "count": len(cards), "cards": cards}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"))
    print(f"wrote {len(cards)} cards to {out} ({out.stat().st_size // 1024} KiB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
