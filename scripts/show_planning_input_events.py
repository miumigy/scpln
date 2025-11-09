#!/usr/bin/env python3
"""
PlanningInputSet のイベント履歴を表示するCLI。
"""

from __future__ import annotations

import argparse
import json
import sys

from core.config.storage import (
    get_planning_input_set,
    list_planning_input_set_events,
    PlanningInputSetNotFoundError,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show PlanningInputSet event history",
    )
    parser.add_argument(
        "--label",
        required=True,
        help="planning_input_sets.label",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="number of events to fetch (default: 50)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="output as JSON",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        input_set = get_planning_input_set(label=args.label, include_aggregates=False)
    except PlanningInputSetNotFoundError:
        print(f"Input set '{args.label}' not found.", file=sys.stderr)
        return 1

    events = list_planning_input_set_events(input_set.id, limit=args.limit)
    if args.json:
        payload = {
            "input_set": {
                "id": input_set.id,
                "label": input_set.label,
                "config_version_id": input_set.config_version_id,
                "status": input_set.status,
            },
            "events": [
                {
                    "id": e.id,
                    "action": e.action,
                    "actor": e.actor,
                    "comment": e.comment,
                    "created_at": e.created_at,
                    "metadata": e.metadata,
                }
                for e in events
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            f"Input Set {input_set.label} (id={input_set.id}, status={input_set.status})"
        )
        for ev in events:
            ts = ev.created_at or 0
            actor = ev.actor or "-"
            comment = ev.comment or "-"
            print(f"- [{ts}] {ev.action} by {actor} | comment={comment}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
