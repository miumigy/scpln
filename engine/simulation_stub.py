from __future__ import annotations

from typing import Any, Dict, List, Tuple

from domain.models import SimulationInput


def run_stub(
    payload: SimulationInput, *, include_trace: bool = False
) -> Tuple[
    Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]
]:
    """軽量サマリを生成するスタブ版シミュレーション。

    SCPLN_SKIP_SIMULATION_API=1 のときにテスト用で使用する。
    """

    horizon = max(int(getattr(payload, "planning_horizon", 1) or 1), 1)
    customer_demand = list(getattr(payload, "customer_demand", []) or [])
    products = list(getattr(payload, "products", []) or [])

    daily_demand = [0.0 for _ in range(horizon)]
    demand_total = 0.0
    for demand in customer_demand:
        per_day = float(getattr(demand, "demand_mean", 0.0) or 0.0)
        start = getattr(demand, "start_day", None) or 1
        end = getattr(demand, "end_day", None) or horizon
        start = max(1, start)
        end = min(horizon, end)
        if end < start:
            continue
        for idx in range(start - 1, end):
            daily_demand[idx] += per_day
            demand_total += per_day

    demand_per_day = demand_total / horizon if horizon else 0.0

    # デフォルト単価（最初の製品の sales_price を優先）
    price = next(
        (
            float(getattr(p, "sales_price", 0.0) or 0.0)
            for p in products
            if getattr(p, "sales_price", None) is not None
        ),
        100.0,
    )
    cost_unit = next(
        (
            float(getattr(p, "unit_cost", 0.0) or 0.0)
            for p in products
            if getattr(p, "unit_cost", None) is not None
        ),
        0.0,
    )
    if cost_unit <= 0:
        cost_unit = price * 0.25

    if demand_total <= 0:
        fill_rate = 1.0
    else:
        # 需要が高まると fill_rate が下がる単調減少関数（テスト向けに単純化）
        fill_rate = 1.0 - (demand_per_day / (demand_per_day + 20.0))
        fill_rate = max(0.0, min(1.0, fill_rate))

    sales_total = demand_total * fill_rate
    shortage_total = max(0.0, demand_total - sales_total)
    revenue_total = sales_total * price

    material_total = sales_total * cost_unit
    sgna_total = revenue_total * 0.25
    penalty_total = shortage_total * price * 0.1
    cost_total = material_total + sgna_total + penalty_total
    profit_total = revenue_total - cost_total
    profit_per_day_avg = profit_total / horizon if horizon else profit_total

    summary: Dict[str, Any] = {
        "fill_rate": fill_rate,
        "revenue_total": revenue_total,
        "cost_total": cost_total,
        "sgna_total": sgna_total,
        "penalty_total": penalty_total,
        "profit_total": profit_total,
        "profit_per_day_avg": profit_per_day_avg,
        "store_demand_total": demand_total,
        "store_sales_total": sales_total,
        "customer_shortage_total": shortage_total,
    }

    item_name = getattr(products[0], "name", "item") if products else "item"
    results: List[Dict[str, Any]] = []
    daily_profit_loss: List[Dict[str, Any]] = []
    cost_trace: List[Dict[str, Any]] = []
    for day in range(horizon):
        demand_today = daily_demand[day]
        sales_today = demand_today * fill_rate
        shortage_today = max(0.0, demand_today - sales_today)
        revenue_today = sales_today * price
        material_today = sales_today * cost_unit
        service_today = revenue_today * 0.25
        penalty_today = shortage_today * price * 0.1
        cost_today = material_today + service_today + penalty_today
        profit_today = revenue_today - cost_today

        results.append(
            {
                "day": day,
                "demand": demand_today,
                "sales": sales_today,
                "shortage": shortage_today,
                "fill_rate": fill_rate,
            }
        )
        daily_profit_loss.append(
            {
                "day": day,
                "revenue": revenue_today,
                "cost": cost_today,
                "profit": profit_today,
                "material_cost": material_today,
                "sgna_cost": service_today,
            }
        )

        if include_trace:
            cost_trace.append(
                {
                    "day": day,
                    "node": "stub",
                    "item": item_name,
                    "event": "sale",
                    "qty": sales_today,
                    "unit_cost": round(cost_unit, 6),
                    "amount": round(material_today, 6),
                    "account": "material",
                }
            )
            cost_trace.append(
                {
                    "day": day,
                    "node": "stub",
                    "item": item_name,
                    "event": "sale_sgna",
                    "qty": sales_today,
                    "unit_cost": (
                        round(service_today / sales_today, 6) if sales_today else 0.0
                    ),
                    "amount": round(service_today, 6),
                    "account": "sgna",
                }
            )

    return summary, results, daily_profit_loss, cost_trace
