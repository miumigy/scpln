from __future__ import annotations

from typing import Any, Dict, List, Tuple

from domain.models import SimulationInput


def run_stub(
    payload: SimulationInput, *, include_trace: bool = False
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """軽量サマリを生成するスタブ版シミュレーション。

    SCPLN_SKIP_SIMULATION_API=1 のときにテスト用で使用する。
    """

    horizon = max(int(getattr(payload, "planning_horizon", 1) or 1), 1)
    customer_demand = list(getattr(payload, "customer_demand", []) or [])
    products = list(getattr(payload, "products", []) or [])

    demand_per_day = sum(float(getattr(d, "demand_mean", 0.0) or 0.0) for d in customer_demand)
    demand_total = demand_per_day * horizon

    # デフォルト単価（最初の製品の sales_price を優先）
    price = next(
        (
            float(getattr(p, "sales_price", 0.0) or 0.0)
            for p in products
            if getattr(p, "sales_price", None) is not None
        ),
        100.0,
    )

    if demand_total <= 0:
        fill_rate = 1.0
    else:
        # 需要が高まると fill_rate が下がる単調減少関数（テスト向けに単純化）
        fill_rate = 1.0 - (demand_per_day / (demand_per_day + 20.0))
        fill_rate = max(0.0, min(1.0, fill_rate))

    sales_total = demand_total * fill_rate
    shortage_total = max(0.0, demand_total - sales_total)
    revenue_total = sales_total * price

    service_cost = revenue_total * 0.25
    penalty_total = shortage_total * price * 0.1
    cost_total = service_cost + penalty_total
    profit_total = revenue_total - cost_total
    profit_per_day_avg = profit_total / horizon if horizon else profit_total

    summary: Dict[str, Any] = {
        "fill_rate": fill_rate,
        "revenue_total": revenue_total,
        "cost_total": cost_total,
        "penalty_total": penalty_total,
        "profit_total": profit_total,
        "profit_per_day_avg": profit_per_day_avg,
        "store_demand_total": demand_total,
        "store_sales_total": sales_total,
        "customer_shortage_total": shortage_total,
    }

    day_sales = sales_total / horizon if horizon else sales_total
    day_shortage = shortage_total / horizon if horizon else shortage_total
    day_revenue = day_sales * price
    day_cost = day_revenue * 0.25 + day_shortage * price * 0.1
    day_profit = day_revenue - day_cost

    results: List[Dict[str, Any]] = []
    daily_profit_loss: List[Dict[str, Any]] = []
    for day in range(horizon):
        results.append(
            {
                "day": day,
                "demand": demand_per_day,
                "sales": day_sales,
                "shortage": day_shortage,
                "fill_rate": fill_rate,
            }
        )
        daily_profit_loss.append(
            {
                "day": day,
                "revenue": day_revenue,
                "cost": day_cost,
                "profit": day_profit,
            }
        )

    cost_trace: List[Dict[str, Any]] = []
    if include_trace:
        item_name = (
            getattr(products[0], "name", "item")
            if products
            else "item"
        )
        for day in range(horizon):
            cost_trace.append(
                {
                    "day": day,
                    "node": "stub",
                    "item": item_name,
                    "event": "sale",
                    "qty": day_sales,
                    "unit_cost": round(price * 0.25, 6),
                    "amount": round(day_cost, 6),
                    "account": "COGS",
                }
            )

    return summary, results, daily_profit_loss, cost_trace
