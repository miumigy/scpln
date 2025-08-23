#!/usr/bin/env python3
import json
import os
from pathlib import Path

from app import db


def load_json(p: Path):
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def main():
    base = Path(__file__).resolve().parents[1]
    prod_path = base / "configs" / "product_hierarchy.json"
    loc_path = base / "configs" / "location_hierarchy.json"
    if prod_path.exists():
        mapping = load_json(prod_path)
        db.set_product_hierarchy(mapping)
        print(f"seeded product_hierarchy from {prod_path}")
    else:
        print("product_hierarchy.json not found; skipping")
    if loc_path.exists():
        mapping = load_json(loc_path)
        db.set_location_hierarchy(mapping)
        print(f"seeded location_hierarchy from {loc_path}")
    else:
        print("location_hierarchy.json not found; skipping")


if __name__ == "__main__":
    main()

