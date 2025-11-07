from __future__ import annotations

import math
from typing import List, Optional


def round_quantity(value: float | int, *, mode: str = "int") -> float | int:
    try:
        v = float(value)
    except Exception:
        v = 0.0
    if mode == "none":
        return round(v, 6)
    if mode == "int":
        return int(round(v))
    if mode.startswith("dec"):
        try:
            digits = int(mode[3:])
        except Exception:
            digits = 2
        return round(v, max(0, digits))
    return round(v, 6)


def distribute_int(
    values: List[float],
    target: int | float,
    caps: Optional[List[int | float]] = None,
) -> List[int]:
    if not values:
        return []
    n = len(values)
    target_int = max(0, int(round_quantity(target, mode="int")))
    caps_norm: List[int]
    if caps is None:
        caps_norm = [target_int] * n
    else:
        caps_norm = [max(0, int(round_quantity(c, mode="int"))) for c in caps]
    ints = []
    total = 0
    for idx, val in enumerate(values):
        v = max(0.0, float(val))
        base = int(math.floor(v))
        cap = caps_norm[idx]
        if base > cap:
            base = cap
        ints.append(base)
        total += base
    diff = target_int - total

    def frac(i: int) -> float:
        v = max(0.0, float(values[i]))
        return v - math.floor(v)

    if diff > 0:
        order = sorted(range(n), key=lambda i: frac(i), reverse=True)
        for idx in order:
            if diff <= 0:
                break
            room = caps_norm[idx] - ints[idx]
            if room <= 0:
                continue
            take = min(room, diff)
            ints[idx] += take
            diff -= take
            if diff <= 0:
                break
    elif diff < 0:
        order = sorted(range(n), key=lambda i: frac(i))
        for idx in order:
            while diff < 0 and ints[idx] > 0:
                ints[idx] -= 1
                diff += 1
                if diff == 0:
                    break
            if diff == 0:
                break
    return ints
