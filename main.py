from app.api import app
from domain.models import SimulationInput
from engine.simulator import SupplyChainSimulator
import logging
import math
from collections import defaultdict

try:
    import app.metrics  # noqa: F401  # /metrics を副作用で登録
except Exception:
    pass

try:
    import app.simulation_api  # noqa: F401
except Exception:
    pass


__all__ = ["app", "SimulationInput", "SupplyChainSimulator"]


if __name__ == "__main__":
    import json

    logging.basicConfig(
        level=logging.DEBUG,
        filename="simulation.log",
        filemode="w",
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    print("--- Script started ---")

    with open("static/default_input.json", encoding="utf-8") as f:
        sim_input_dict = json.load(f)
    sim_input = SimulationInput(**sim_input_dict)

    simulator = SupplyChainSimulator(sim_input)
    results, profit_loss = simulator.run()

    logging.info("--- SIMULATION TEST COMPLETE ---")
    logging.info("--- PROFIT/LOSS DATA ---")
    for day_pl in profit_loss:
        logging.info(day_pl)

    # 期末未着は pending_shipments（シミュ後日付）から集計
    in_transit_at_end = defaultdict(float)
    for arrival_day, orders in simulator.pending_shipments.items():
        for rec in orders:
            if len(rec) == 4:
                item, qty, _src, dest = rec
            else:
                item, qty, _src, dest, _is_bo = rec
            in_transit_at_end[(dest, item)] += qty

    logging.info("CUMULATIVE ORDERED:")
    logging.info(simulator.cumulative_ordered)
    logging.info("CUMULATIVE RECEIVED:")
    logging.info(simulator.cumulative_received)
    logging.info("IN TRANSIT AT END:")
    logging.info(in_transit_at_end)

    validation_passed = True
    all_keys = set(simulator.cumulative_ordered.keys()) | set(
        simulator.cumulative_received.keys()
    )

    for key in all_keys:
        ordered = simulator.cumulative_ordered.get(key, 0)
        received = simulator.cumulative_received.get(key, 0)
        in_transit = in_transit_at_end.get(key, 0)

        if not math.isclose(ordered, received + in_transit, rel_tol=1e-9, abs_tol=1e-9):
            validation_passed = False
            logging.error(
                f"VALIDATION FAILED for {key}: Ordered={ordered}, Received={received}, InTransit={in_transit}"
            )

    if validation_passed:
        logging.info(
            "*** VALIDATION SUCCESS: Cumulative Ordered == Cumulative Received + In-Transit at End ***"
        )
    else:
        logging.info("*** VALIDATION FAILURE ***")
