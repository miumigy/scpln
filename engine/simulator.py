import logging
import math
import random
from collections import defaultdict

try:
    from scipy.stats import norm as _scipy_norm  # type: ignore

    norm_ppf = _scipy_norm.ppf
except Exception:  # pragma: no cover
    from statistics import NormalDist

    norm_ppf = NormalDist().inv_cdf


def _service_level_z(p: float) -> float:
    if p is None:
        return 0.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 6.0
    return float(norm_ppf(p))


from domain.models import (
    SimulationInput,
    StoreNode,
    WarehouseNode,
    MaterialNode,
    FactoryNode,
)


class SupplyChainSimulator:
    def __init__(self, sim_input: SimulationInput):
        self.input = sim_input
        self.products = {p.name: p for p in self.input.products}
        self.nodes_map = {n.name: n for n in self.input.nodes}
        self.network_map = {
            (link.from_node, link.to_node): link for link in self.input.network
        }

        self.stock = {
            n.name: defaultdict(float, n.initial_stock) for n in self.input.nodes
        }
        self.production_orders = defaultdict(
            list
        )  # {completion_day: [(item, qty, factory)]}
        self.order_history = defaultdict(
            list
        )  # {day: [(item, qty, from_node, to_node)]}
        # Pending outbound shipments scheduled by ship day. Each entry:
        #   (item_name, qty, supplier_node_name, dest_node_name, is_backorder)
        self.pending_shipments = defaultdict(list)  # {ship_day: [tuple]}
        self.customer_backorders = defaultdict(lambda: defaultdict(float))

        self.cumulative_ordered = defaultdict(float)
        self.cumulative_received = defaultdict(float)

        self.daily_results = []
        self.daily_profit_loss = []
        self.node_order = self._get_topological_order()
        self.warehouse_demand_profiles = self._calculate_warehouse_demand_profiles()
        self.factory_demand_profiles = self._calculate_factory_demand_profiles()

    def _get_topological_order(self):
        order = []
        node_types = ["store", "warehouse", "factory", "material"]
        for n_type in node_types:
            for node in self.input.nodes:
                if node.node_type == n_type and node.name not in order:
                    order.append(node.name)
        return order

    def _calculate_warehouse_demand_profiles(self):
        profiles = defaultdict(lambda: defaultdict(lambda: {"mean": 0, "variance": 0}))
        for wh in [n for n in self.input.nodes if n.node_type == "warehouse"]:
            for link in self.input.network:
                if (
                    link.from_node == wh.name
                    and self.nodes_map[link.to_node].node_type == "store"
                ):
                    store_name = link.to_node
                    for demand in self.input.customer_demand:
                        if demand.store_name == store_name:
                            profiles[wh.name][demand.product_name][
                                "mean"
                            ] += demand.demand_mean
                            profiles[wh.name][demand.product_name]["variance"] += (
                                demand.demand_std_dev**2
                            )
        for _, products in profiles.items():
            for _, data in products.items():
                data["std_dev"] = math.sqrt(data["variance"])
        return profiles

    def _calculate_factory_demand_profiles(self):
        profiles = defaultdict(lambda: defaultdict(lambda: {"mean": 0, "variance": 0}))
        for factory in [n for n in self.input.nodes if n.node_type == "factory"]:
            for link in self.input.network:
                if (
                    link.from_node == factory.name
                    and self.nodes_map[link.to_node].node_type == "warehouse"
                ):
                    wh_name = link.to_node
                    wh_profile = self.warehouse_demand_profiles.get(wh_name, {})
                    for item, data in wh_profile.items():
                        if item in factory.producible_products:
                            profiles[factory.name][item]["mean"] += data["mean"]
                            profiles[factory.name][item]["variance"] += data["variance"]
        for _, products in profiles.items():
            for _, data in products.items():
                data["std_dev"] = math.sqrt(data["variance"])
        return profiles

    def run(self):
        if getattr(self.input, "random_seed", None) is not None:
            try:
                random.seed(self.input.random_seed)
            except Exception:
                pass
        for day in range(self.input.planning_horizon):
            start_of_day_stock = {
                name: self.stock[name].copy() for name in self.nodes_map
            }
            daily_events = defaultdict(lambda: defaultdict(float))

            logging.debug(f"--- Day {day}: Receiving Orders ---")
            received_orders_today = defaultdict(list)
            # in_transit_orders は廃止済み

            if day in self.pending_shipments:
                shipped_so_far = defaultdict(float)
                dest_incoming_today = defaultdict(float)
                for rec in self.pending_shipments.pop(day):
                    if len(rec) == 4:
                        item, qty, supplier_name, dest_name = rec
                        is_backorder = False
                    else:
                        item, qty, supplier_name, dest_name, is_backorder = rec

                    link_obj = self.network_map.get((supplier_name, dest_name))
                    supplier_node = self.nodes_map[supplier_name]
                    dest_node = self.nodes_map[dest_name]
                    available = self.stock[supplier_name].get(item, 0)
                    request_qty = min(available, qty)

                    link_cap = (
                        getattr(link_obj, "capacity_per_day", float("inf"))
                        if link_obj
                        else float("inf")
                    )
                    link_allow_over = (
                        getattr(link_obj, "allow_over_capacity", True)
                        if link_obj
                        else True
                    )
                    remaining_link_cap = max(
                        0.0, link_cap - shipped_so_far[(supplier_name, dest_name)]
                    )

                    shipped_candidate = request_qty
                    link_over_qty = 0.0
                    if not link_allow_over:
                        shipped_candidate = min(shipped_candidate, remaining_link_cap)
                    else:
                        if remaining_link_cap < shipped_candidate:
                            link_over_qty = shipped_candidate - remaining_link_cap

                    storage_cap = getattr(dest_node, "storage_capacity", float("inf"))
                    storage_allow_over = getattr(
                        dest_node, "allow_storage_over_capacity", True
                    )
                    total_stock_now = sum(self.stock[dest_name].values())
                    remaining_storage = max(
                        0.0,
                        storage_cap
                        - (total_stock_now + dest_incoming_today[dest_name]),
                    )
                    storage_over_add = 0.0
                    if not storage_allow_over:
                        shipped_candidate = min(shipped_candidate, remaining_storage)

                    shipped = max(0.0, min(request_qty, shipped_candidate))

                    daily_events[f"{supplier_name}_{item}"]["demand"] += qty
                    if shipped > 0:
                        self.stock[supplier_name][item] -= shipped
                        daily_events[f"{supplier_name}_{item}"]["sales"] += shipped

                        shipped_so_far[(supplier_name, dest_name)] += shipped
                        dest_incoming_today[dest_name] += shipped

                        if storage_allow_over and storage_cap != float("inf"):
                            before_over = max(
                                0.0,
                                (
                                    total_stock_now
                                    + dest_incoming_today[dest_name]
                                    - shipped
                                )
                                - storage_cap,
                            )
                            after_over = max(
                                0.0,
                                (total_stock_now + dest_incoming_today[dest_name])
                                - storage_cap,
                            )
                            storage_over_add = max(0.0, after_over - before_over)
                            if storage_over_add > 0:
                                skey = f"storage_overage:{dest_name}"
                                if skey not in daily_events:
                                    daily_events[skey] = {"qty": 0.0}
                                daily_events[skey]["qty"] += storage_over_add

                        self.stock[dest_name][item] += shipped
                        daily_events[f"{dest_name}_{item}"]["incoming"] += shipped
                        tkey = f"transport:{supplier_name}->{dest_name}:{item}"
                        if tkey not in daily_events:
                            daily_events[tkey] = {"qty": 0.0}
                        daily_events[tkey]["qty"] += shipped

                        if link_allow_over and link_cap != float("inf"):
                            before_over_link = max(
                                0.0,
                                (shipped_so_far[(supplier_name, dest_name)] - shipped)
                                - link_cap,
                            )
                            after_over_link = max(
                                0.0,
                                shipped_so_far[(supplier_name, dest_name)] - link_cap,
                            )
                            over_added = max(0.0, after_over_link - before_over_link)
                            if over_added > 0:
                                okey = f"transport_overage:{supplier_name}->{dest_name}"
                                if okey not in daily_events:
                                    daily_events[okey] = {"qty": 0.0}
                                daily_events[okey]["qty"] += over_added

                    if qty > shipped:
                        shortage = qty - shipped
                        daily_events[f"{supplier_name}_{item}"]["shortage"] += shortage
                        logging.debug(
                            f"Day {day}: Supplier {supplier_name} shortage {shortage} of {item} for {dest_name}"
                        )
                        if getattr(supplier_node, "backorder_enabled", True):
                            self.pending_shipments[day + 1].append(
                                (item, shortage, supplier_name, dest_name, True)
                            )

            # Legacy in_transit_orders 経路は廃止（pending_shipmentsに統一）
            for item, qty, factory_name in self.production_orders.pop(day, []):
                factory_node = self.nodes_map[factory_name]
                storage_cap = getattr(factory_node, "storage_capacity", float("inf"))
                allow_over = getattr(factory_node, "allow_storage_over_capacity", True)
                total_stock_now = sum(self.stock[factory_name].values())
                remaining_storage = max(0.0, storage_cap - total_stock_now)
                to_store = qty
                if not allow_over:
                    to_store = min(qty, remaining_storage)
                if to_store > 0:
                    self.stock[factory_name][item] += to_store
                    daily_events[f"{factory_name}_{item}"]["produced"] += to_store
                    if allow_over and storage_cap != float("inf"):
                        over_after = max(
                            0.0, (total_stock_now + to_store) - storage_cap
                        )
                        over_before = max(0.0, total_stock_now - storage_cap)
                        over_add = max(0.0, over_after - over_before)
                        if over_add > 0:
                            skey = f"storage_overage:{factory_name}"
                            if skey not in daily_events:
                                daily_events[skey] = {"qty": 0.0}
                            daily_events[skey]["qty"] += over_add
                if to_store < qty and not allow_over:
                    remaining = qty - to_store
                    self.production_orders[day + 1].append(
                        (item, remaining, factory_name)
                    )

            for node in self.input.nodes:
                if node.node_type == "store":
                    store = node.name
                    for item_name, bo_qty in list(
                        self.customer_backorders[store].items()
                    ):
                        if bo_qty <= 0:
                            continue
                        available = self.stock[store].get(item_name, 0)
                        shipped = min(available, bo_qty)
                        if shipped > 0:
                            self.stock[store][item_name] -= shipped
                            self.customer_backorders[store][item_name] -= shipped
                            daily_events[f"{store}_{item_name}"]["sales"] += shipped

            logging.debug(f"--- Day {day}: Customer Demand ---")
            demand_signals = defaultdict(
                lambda: defaultdict(lambda: defaultdict(float))
            )
            for cd in self.input.customer_demand:
                demand_qty = max(
                    0, round(random.gauss(cd.demand_mean, cd.demand_std_dev))
                )
                if demand_qty > 0:
                    store_name, item_name = cd.store_name, cd.product_name
                    logging.debug(
                        f"Day {day}: Customer demand of {demand_qty} for {item_name} at {store_name}"
                    )
                    daily_events[f"{store_name}_{item_name}"]["demand"] += demand_qty
                    available = self.stock[store_name].get(item_name, 0)
                    shipped = min(available, demand_qty)
                    if shipped > 0:
                        self.stock[store_name][item_name] -= shipped
                        daily_events[f"{store_name}_{item_name}"]["sales"] += shipped
                        logging.debug(
                            f"Day {day}: Shipped {shipped} of {item_name} to customer from {store_name}"
                        )
                    if demand_qty > shipped:
                        daily_events[f"{store_name}_{item_name}"]["shortage"] += (
                            demand_qty - shipped
                        )
                        logging.debug(
                            f"Day {day}: Shortage of {demand_qty - shipped} for {item_name} at {store_name}"
                        )
                        node_obj = self.nodes_map.get(store_name)
                        # lost_sales=true の場合はバックオーダーを積まない
                        if getattr(node_obj, "backorder_enabled", True) and not getattr(
                            node_obj, "lost_sales", False
                        ):
                            self.customer_backorders[store_name][item_name] += (
                                demand_qty - shipped
                            )

            logging.debug(f"--- Day {day}: Planning & Ordering ---")

            for node_name in self.node_order:
                current_node = self.nodes_map[node_name]

                if node_name in demand_signals:
                    logging.debug(
                        f"Day {day}: Fulfilling customer demand for {node_name}"
                    )
                    for item_name, requesters in demand_signals[node_name].items():
                        for requester_name, demand_qty in requesters.items():
                            logging.debug(
                                f"Day {day}: Processing demand for {item_name} from {requester_name} with qty {demand_qty}"
                            )
                            logging.debug(
                                f"Day {day}: Demand of {demand_qty} for {item_name} from {requester_name} to {node_name}"
                            )
                        available = self.stock[node_name].get(item_name, 0)
                        shipped = min(available, demand_qty)
                        if shipped > 0:
                            self.stock[node_name][item_name] -= shipped
                            daily_events[f"{node_name}_{item_name}"]["sales"] += shipped
                            self.cumulative_received[
                                (requester_name, item_name)
                            ] += shipped
                            demand_signals[node_name][item_name][
                                requester_name
                            ] -= shipped
                        if demand_qty > shipped:
                            daily_events[f"{node_name}_{item_name}"]["shortage"] += (
                                demand_qty - shipped
                            )
                            logging.debug(
                                f"Day {day}: Shortage of {demand_qty - shipped} for {item_name} at {node_name}"
                            )

                items_to_manage = set(current_node.initial_stock.keys())
                if isinstance(current_node, (StoreNode, WarehouseNode)):
                    logging.debug(f"Day {day}: Replenishment planning for {node_name}")
                    for item_name in items_to_manage:
                        parent_name = next(
                            (
                                l.from_node
                                for l in self.input.network
                                if l.to_node == node_name
                            ),
                            None,
                        )
                        if not parent_name:
                            continue
                        link_obj = self.network_map.get((parent_name, node_name))
                        replenishment_lt = link_obj.lead_time if link_obj else 0
                        review_R = getattr(current_node, "review_period_days", 0) or 0

                        profile = (
                            self.warehouse_demand_profiles.get(node_name, {}).get(
                                item_name
                            )
                            if isinstance(current_node, WarehouseNode)
                            else next(
                                (
                                    d
                                    for d in self.input.customer_demand
                                    if d.store_name == node_name
                                    and d.product_name == item_name
                                ),
                                None,
                            )
                        )
                        if not profile:
                            continue
                        demand_mean = (
                            profile["mean"]
                            if isinstance(profile, dict)
                            else profile.demand_mean
                        )
                        demand_std = (
                            profile["std_dev"]
                            if isinstance(profile, dict)
                            else profile.demand_std_dev
                        )

                        inv_on_hand = self.stock[node_name].get(item_name, 0)
                        pipeline_incoming = 0.0
                        for d, orders in self.pending_shipments.items():
                            if d > day:
                                for rec in orders:
                                    if len(rec) == 4:
                                        it, q, _src, dest = rec
                                    else:
                                        it, q, _src, dest, _is_bo = rec
                                    if dest == node_name and it == item_name:
                                        pipeline_incoming += q
                        # in_transit_orders 統合に伴い pending_shipments のみを参照
                        scheduled_outgoing = 0.0
                        for d, orders in self.pending_shipments.items():
                            if d > day:
                                for rec in orders:
                                    if len(rec) == 4:
                                        it, q, supplier, _dest = rec
                                        is_bo = False
                                    else:
                                        it, q, supplier, _dest, is_bo = rec
                                    if supplier == node_name and it == item_name:
                                        scheduled_outgoing += q
                        inv_pos = inv_on_hand + pipeline_incoming
                        if isinstance(current_node, StoreNode):
                            # lost_sales=false のときのみ顧客BOを控除
                            if not getattr(current_node, "lost_sales", False):
                                inv_pos -= self.customer_backorders[node_name].get(
                                    item_name, 0.0
                                )
                        elif isinstance(current_node, WarehouseNode):
                            inv_pos -= scheduled_outgoing
                        z = _service_level_z(current_node.service_level)
                        # 互換性維持のため μ*(L+R+1)
                        eff_LR = max(0.0, (replenishment_lt + review_R))
                        order_up_to = z * demand_std * math.sqrt(
                            eff_LR
                        ) + demand_mean * (eff_LR + 1)
                        qty_to_order = max(0, math.ceil(order_up_to - inv_pos))
                        logging.debug(
                            f"Day {day}: Node {node_name}, Item {item_name}: inv_pos={inv_pos}, order_up_to={order_up_to}, calculated qty_to_order={qty_to_order}"
                        )

                        if qty_to_order > 0:
                            node_moq = getattr(current_node, "moq", {}).get(
                                item_name, 0
                            )
                            node_mult = getattr(current_node, "order_multiple", {}).get(
                                item_name, 0
                            )
                            link_moq = (
                                getattr(link_obj, "moq", {}).get(item_name, 0)
                                if link_obj
                                else 0
                            )
                            link_mult = (
                                getattr(link_obj, "order_multiple", {}).get(
                                    item_name, 0
                                )
                                if link_obj
                                else 0
                            )

                            effective_moq = max(node_moq or 0, link_moq or 0)
                            if 0 < qty_to_order < effective_moq:
                                qty_to_order = effective_moq

                            def _is_int(x: float) -> bool:
                                return math.isclose(x, round(x))

                            eff_mult = 0
                            if (node_mult or 0) > 0 and (link_mult or 0) > 0:
                                if _is_int(node_mult) and _is_int(link_mult):
                                    a, b = int(round(node_mult)), int(round(link_mult))
                                    eff_mult = abs(a * b) // math.gcd(a, b)
                                else:
                                    eff_mult = 0
                            if eff_mult:
                                qty_to_order = int(
                                    math.ceil(qty_to_order / eff_mult) * eff_mult
                                )
                            else:
                                for m in [node_mult, link_mult]:
                                    if m and m > 0:
                                        qty_to_order = int(
                                            math.ceil(qty_to_order / m) * m
                                        )
                            self._place_order(
                                parent_name, node_name, item_name, qty_to_order, day
                            )

                if isinstance(current_node, FactoryNode):
                    # Finished goods production planning based on downstream aggregated demand
                    factory_profile = self.factory_demand_profiles.get(node_name, {})
                    for fg_item in current_node.producible_products:
                        profile = factory_profile.get(fg_item)
                        if not profile:
                            continue
                        demand_mean = profile["mean"]
                        demand_std = profile.get("std_dev", 0.0)
                        prod_lt = getattr(current_node, "lead_time", 0)
                        review_R = getattr(current_node, "review_period_days", 0) or 0

                        inv_on_hand = self.stock[node_name].get(fg_item, 0)
                        # Incoming finished goods from previously scheduled production
                        pipeline_incoming = 0.0
                        for d, orders in self.production_orders.items():
                            if d > day:
                                for it, q, fac in orders:
                                    if fac == node_name and it == fg_item:
                                        pipeline_incoming += q
                        # Outgoing commitments (factory -> warehouses)
                        scheduled_outgoing = 0.0
                        for d, orders in self.pending_shipments.items():
                            if d > day:
                                for rec in orders:
                                    if len(rec) == 4:
                                        it, q, supplier, _dest = rec
                                    else:
                                        it, q, supplier, _dest, _is_bo = rec
                                    if supplier == node_name and it == fg_item:
                                        scheduled_outgoing += q

                        inv_pos = inv_on_hand + pipeline_incoming - scheduled_outgoing
                        z = _service_level_z(current_node.service_level)
                        eff_LR = max(0.0, (prod_lt + review_R))
                        order_up_to = z * demand_std * math.sqrt(
                            eff_LR
                        ) + demand_mean * (eff_LR + 1)
                        qty_to_produce = max(0, math.ceil(order_up_to - inv_pos))
                        if qty_to_produce > 0:
                            completion_day = day + prod_lt
                            self.production_orders[completion_day].append(
                                (fg_item, qty_to_produce, node_name)
                            )

                    # Component replenishment planning (Factory -> Material suppliers)
                    for item_name, reorder_point in getattr(
                        current_node, "reorder_point", {}
                    ).items():
                        if reorder_point is None:
                            continue
                        inv_on_hand = self.stock[node_name].get(item_name, 0)
                        # Include pipeline component shipments (pending_shipments)
                        pipeline_incoming = 0.0
                        for d, orders in self.pending_shipments.items():
                            if d > day:
                                for rec in orders:
                                    if len(rec) == 4:
                                        it, q, _src, dest = rec
                                    else:
                                        it, q, _src, dest, _is_bo = rec
                                    if dest == node_name and it == item_name:
                                        pipeline_incoming += q
                        # 統合後は pending_shipments のみ
                        inv_pos = inv_on_hand + pipeline_incoming
                        if inv_pos <= reorder_point:
                            order_up_to = current_node.order_up_to_level.get(
                                item_name, inv_pos
                            )
                            qty_to_order = max(0, order_up_to - inv_pos)
                            if qty_to_order > 0:
                                parent_name = next(
                                    (
                                        l.from_node
                                        for l in self.input.network
                                        if l.to_node == node_name
                                        and self.nodes_map[l.from_node].node_type
                                        == "material"
                                        and item_name
                                        in self.nodes_map[l.from_node].material_cost
                                    ),
                                    None,
                                )
                                if parent_name:
                                    link_obj = self.network_map.get(
                                        (parent_name, node_name)
                                    )
                                    node_moq = getattr(current_node, "moq", {}).get(
                                        item_name, 0
                                    )
                                    node_mult = getattr(
                                        current_node, "order_multiple", {}
                                    ).get(item_name, 0)
                                    link_moq = (
                                        getattr(link_obj, "moq", {}).get(item_name, 0)
                                        if link_obj
                                        else 0
                                    )
                                    link_mult = (
                                        getattr(link_obj, "order_multiple", {}).get(
                                            item_name, 0
                                        )
                                        if link_obj
                                        else 0
                                    )
                                    effective_moq = max(node_moq or 0, link_moq or 0)
                                    if 0 < qty_to_order < effective_moq:
                                        qty_to_order = effective_moq

                                    def _is_int(x: float) -> bool:
                                        return math.isclose(x, round(x))

                                    eff_mult = 0
                                    if (node_mult or 0) > 0 and (link_mult or 0) > 0:
                                        if _is_int(node_mult) and _is_int(link_mult):
                                            a, b = int(round(node_mult)), int(
                                                round(link_mult)
                                            )
                                            eff_mult = abs(a * b) // math.gcd(a, b)
                                        else:
                                            eff_mult = 0
                                    if eff_mult:
                                        qty_to_order = int(
                                            math.ceil(qty_to_order / eff_mult)
                                            * eff_mult
                                        )
                                    else:
                                        for m in [node_mult, link_mult]:
                                            if m and m > 0:
                                                qty_to_order = int(
                                                    math.ceil(qty_to_order / m) * m
                                                )
                                    self._place_order(
                                        parent_name,
                                        node_name,
                                        item_name,
                                        qty_to_order,
                                        day,
                                    )

            self.record_daily_snapshot(
                day, start_of_day_stock, self.stock, daily_events
            )
            self.calculate_daily_profit_loss(day, daily_events)

        return self.daily_results, self.daily_profit_loss

    def _place_order(
        self,
        supplier_node_name: str,
        customer_node_name: str,
        item_name: str,
        quantity: float,
        current_day: int,
    ):
        logging.debug(
            f"DEBUG: Day {current_day}: Placing order for {item_name} qty {quantity} from {supplier_node_name} to {customer_node_name}."
        )
        self.order_history[current_day].append(
            (item_name, quantity, supplier_node_name, customer_node_name)
        )
        self.cumulative_ordered[(customer_node_name, item_name)] += quantity
        link_obj = self.network_map.get((supplier_node_name, customer_node_name))
        link_lt = link_obj.lead_time if link_obj else 0
        ship_day = current_day + link_lt
        self.pending_shipments[ship_day].append(
            (item_name, quantity, supplier_node_name, customer_node_name, False)
        )

    def compute_summary(self):
        node_type_map = {name: n.node_type for name, n in self.nodes_map.items()}
        totals_by_type = {
            t: {"demand": 0.0, "sales": 0.0, "shortage": 0.0, "end_stock_sum": 0.0}
            for t in ("store", "warehouse", "factory", "material")
        }
        top_shortage_by_item = defaultdict(float)
        backorder_total_by_day = []

        for day in self.daily_results:
            bo_day_total = 0.0
            for node_name, items in day.get("nodes", {}).items():
                ntype = node_type_map.get(node_name)
                if not ntype:
                    continue
                for item_name, m in items.items():
                    d = m.get("demand", 0) or 0
                    s = m.get("sales", 0) or 0
                    sh = m.get("shortage", 0) or 0
                    end = m.get("end_stock", 0) or 0
                    totals_by_type[ntype]["demand"] += d
                    totals_by_type[ntype]["sales"] += s
                    totals_by_type[ntype]["shortage"] += sh
                    totals_by_type[ntype]["end_stock_sum"] += end
                    if ntype == "store":
                        top_shortage_by_item[item_name] += sh
                        bo_day_total += m.get("backorder_balance", 0) or 0
            backorder_total_by_day.append(bo_day_total)

        days = max(1, len(self.daily_results))
        avg_on_hand_by_type = {
            t: totals_by_type[t]["end_stock_sum"] / days for t in totals_by_type
        }
        store_demand = totals_by_type["store"]["demand"]
        store_sales = totals_by_type["store"]["sales"]
        fill_rate = (store_sales / store_demand) if store_demand > 0 else 1.0

        total_revenue = sum(pl.get("revenue", 0) or 0 for pl in self.daily_profit_loss)
        total_material = sum(
            pl.get("material_cost", 0) or 0 for pl in self.daily_profit_loss
        )
        total_flow = sum(
            sum((pl.get("flow_costs", {}) or {}).values())
            for pl in self.daily_profit_loss
        )
        total_stock = sum(
            sum((pl.get("stock_costs", {}) or {}).values())
            for pl in self.daily_profit_loss
        )
        total_penalty_stockout = sum(
            ((pl.get("penalty_costs", {}) or {}).get("stockout", 0) or 0)
            for pl in self.daily_profit_loss
        )
        total_penalty_backorder = sum(
            ((pl.get("penalty_costs", {}) or {}).get("backorder", 0) or 0)
            for pl in self.daily_profit_loss
        )
        total_penalty = total_penalty_stockout + total_penalty_backorder
        total_cost = total_material + total_flow + total_stock + total_penalty
        total_profit = total_revenue - total_cost

        top_short = sorted(top_shortage_by_item.items(), key=lambda x: -x[1])[:5]

        summary = {
            "planning_days": days,
            "fill_rate": fill_rate,
            "store_demand_total": store_demand,
            "store_sales_total": store_sales,
            "customer_shortage_total": totals_by_type["store"]["shortage"],
            "network_shortage_total": sum(
                totals_by_type[t]["shortage"]
                for t in ("warehouse", "factory", "material")
            ),
            "avg_on_hand_by_type": avg_on_hand_by_type,
            "backorder_peak": (
                max(backorder_total_by_day) if backorder_total_by_day else 0
            ),
            "backorder_peak_day": (
                (backorder_total_by_day.index(max(backorder_total_by_day)) + 1)
                if backorder_total_by_day
                else 0
            ),
            "revenue_total": total_revenue,
            "cost_total": total_cost,
            "penalty_stockout_total": total_penalty_stockout,
            "penalty_backorder_total": total_penalty_backorder,
            "penalty_total": total_penalty,
            "profit_total": total_profit,
            "profit_per_day_avg": total_profit / days if days else 0,
            "top_shortage_items": [
                {"item": it, "shortage": qty} for it, qty in top_short
            ],
        }
        return summary

    def record_daily_snapshot(self, day, start_stock, end_stock, events):
        snapshot = {"day": day + 1, "nodes": {}}
        all_node_names = set(start_stock.keys()) | set(end_stock.keys())

        daily_ordered_quantities = defaultdict(lambda: defaultdict(float))
        for item, qty, _supplier, dest in self.order_history.get(day, []):
            if dest in self.nodes_map:
                daily_ordered_quantities[dest][item] += qty

        event_items_by_node = defaultdict(set)
        for key in events.keys():
            if ":" in key:
                continue
            try:
                node_name, item_name = key.split("_", 1)
            except ValueError:
                continue
            event_items_by_node[node_name].add(item_name)

        backorder_balance_map = defaultdict(lambda: defaultdict(float))
        future_days = [d for d in self.pending_shipments.keys() if d >= day + 1]
        for d in future_days:
            for rec in self.pending_shipments.get(d, []):
                if len(rec) == 5:
                    item, qty, supplier, _dest, is_backorder = rec
                    if is_backorder:
                        backorder_balance_map[supplier][item] += qty
        for store_name, items in self.customer_backorders.items():
            for item, qty in items.items():
                if qty > 0:
                    backorder_balance_map[store_name][item] += qty

        for name in sorted(list(all_node_names | set(event_items_by_node.keys()))):
            node_snapshot = {}
            all_items = (
                set(start_stock.get(name, {}).keys())
                | set(end_stock.get(name, {}).keys())
                | set(event_items_by_node.get(name, set()))
            )
            for item in sorted(list(all_items)):
                event_key = f"{name}_{item}"
                item_snapshot = events.get(event_key, defaultdict(float))
                item_snapshot["start_stock"] = start_stock.get(name, {}).get(item, 0)
                item_snapshot["end_stock"] = end_stock.get(name, {}).get(item, 0)
                item_snapshot["ordered_quantity"] = daily_ordered_quantities[name][item]
                for metric in [
                    "incoming",
                    "demand",
                    "sales",
                    "consumption",
                    "produced",
                    "shortage",
                    "backorder_balance",
                ]:
                    if metric not in item_snapshot:
                        item_snapshot[metric] = 0
                item_snapshot["demand"] = item_snapshot.get(
                    "sales", 0
                ) + item_snapshot.get("shortage", 0)
                item_snapshot["backorder_balance"] = backorder_balance_map[name][item]
                node_snapshot[item] = item_snapshot
            if node_snapshot:
                snapshot["nodes"][name] = node_snapshot

        self.daily_results.append(snapshot)

    def calculate_daily_profit_loss(self, day, events):
        pl = {
            "day": day + 1,
            "revenue": 0,
            "material_cost": 0,
            "flow_costs": {
                "material_transport_fixed": 0,
                "material_transport_variable": 0,
                "production_fixed": 0,
                "production_variable": 0,
                "warehouse_transport_fixed": 0,
                "warehouse_transport_variable": 0,
                "store_transport_fixed": 0,
                "store_transport_variable": 0,
            },
            "stock_costs": {
                "material_storage_fixed": 0,
                "material_storage_variable": 0,
                "factory_storage_fixed": 0,
                "factory_storage_variable": 0,
                "warehouse_storage_fixed": 0,
                "warehouse_storage_variable": 0,
                "store_storage_fixed": 0,
                "store_storage_variable": 0,
            },
            "penalty_costs": {
                "stockout": 0,
                "backorder": 0,
            },
            "total_cost": 0,
            "profit_loss": 0,
        }

        produced_by_factory = defaultdict(float)
        nodes_produced = set()
        for key, data in events.items():
            if ":" in key:
                continue
            try:
                node_name, item_name = key.split("_", 1)
            except ValueError:
                continue
            produced_qty = data.get("produced", 0) or 0
            if produced_qty > 0:
                produced_by_factory[node_name] += produced_qty
                nodes_produced.add(node_name)
            sales_qty = data.get("sales", 0) or 0
            if sales_qty > 0 and item_name:
                node = self.nodes_map.get(node_name)
                if isinstance(node, StoreNode):
                    # Revenue handling can be extended via Product.sales_price if needed
                    pass

        transport_costs_by_type = {
            "material_transport": {"fixed": 0.0, "variable": 0.0},
            "warehouse_transport": {"fixed": 0.0, "variable": 0.0},
            "store_transport": {"fixed": 0.0, "variable": 0.0},
        }

        for key, data in events.items():
            if key.startswith("transport:"):
                try:
                    route, item = key.split(":", 1)[1].split(":", 1)
                    supplier_name, dest_name = route.split("->", 1)
                except Exception:
                    continue
                qty = data.get("qty", 0) or 0
                if qty <= 0:
                    continue
                link = self.network_map.get((supplier_name, dest_name))
                if not link:
                    continue
                supplier = self.nodes_map.get(supplier_name)
                dest = self.nodes_map.get(dest_name)
                if isinstance(supplier, MaterialNode) and isinstance(dest, FactoryNode):
                    transport_costs_by_type["material_transport"][
                        "fixed"
                    ] += link.transportation_cost_fixed
                    transport_costs_by_type["material_transport"]["variable"] += (
                        link.transportation_cost_variable * qty
                    )
                    pl["material_cost"] += (
                        getattr(supplier, "material_cost", {}).get(item, 0) * qty
                    )
                elif isinstance(supplier, FactoryNode) and isinstance(
                    dest, WarehouseNode
                ):
                    transport_costs_by_type["warehouse_transport"][
                        "fixed"
                    ] += link.transportation_cost_fixed
                    transport_costs_by_type["warehouse_transport"]["variable"] += (
                        link.transportation_cost_variable * qty
                    )
                elif isinstance(supplier, WarehouseNode) and isinstance(
                    dest, StoreNode
                ):
                    transport_costs_by_type["store_transport"][
                        "fixed"
                    ] += link.transportation_cost_fixed
                    transport_costs_by_type["store_transport"]["variable"] += (
                        link.transportation_cost_variable * qty
                    )

        for node_name in nodes_produced:
            pl["flow_costs"]["production_fixed"] += self.nodes_map[
                node_name
            ].production_cost_fixed

        for node_name, qty_prod in produced_by_factory.items():
            node = self.nodes_map.get(node_name)
            if not isinstance(node, FactoryNode):
                continue
            prod_cap = getattr(node, "production_capacity", float("inf"))
            allow_over = getattr(node, "allow_production_over_capacity", True)
            if prod_cap == float("inf") or not allow_over:
                continue
            over_qty = max(0.0, qty_prod - prod_cap)
            if over_qty > 0:
                pl["flow_costs"]["production_variable"] += (
                    node.production_over_capacity_variable_cost * over_qty
                )
                if node.production_over_capacity_fixed_cost > 0:
                    pl["flow_costs"][
                        "production_fixed"
                    ] += node.production_over_capacity_fixed_cost

        for transport_type, costs in transport_costs_by_type.items():
            pl["flow_costs"][f"{transport_type}_fixed"] = costs["fixed"]
            pl["flow_costs"][f"{transport_type}_variable"] = costs["variable"]

        overage_fixed_applied = set()
        for key, data in events.items():
            if key.startswith("transport_overage:"):
                try:
                    route = key.split(":", 1)[1]
                    supplier_name, dest_name = route.split("->", 1)
                except Exception:
                    continue
                link = self.network_map.get((supplier_name, dest_name))
                if not link:
                    continue
                over_qty = data.get("qty", 0) or 0
                if over_qty <= 0:
                    continue
                supplier = self.nodes_map.get(supplier_name)
                dest = self.nodes_map.get(dest_name)
                if isinstance(supplier, MaterialNode) and isinstance(dest, FactoryNode):
                    ttype = "material_transport"
                elif isinstance(supplier, FactoryNode) and isinstance(
                    dest, WarehouseNode
                ):
                    ttype = "warehouse_transport"
                elif isinstance(supplier, WarehouseNode) and isinstance(
                    dest, StoreNode
                ):
                    ttype = "store_transport"
                else:
                    ttype = None
                if ttype:
                    pl["flow_costs"][f"{ttype}_variable"] += (
                        link.over_capacity_variable_cost * over_qty
                    )
                    lkey = (supplier_name, dest_name)
                    if (
                        lkey not in overage_fixed_applied
                        and link.over_capacity_fixed_cost > 0
                    ):
                        pl["flow_costs"][
                            f"{ttype}_fixed"
                        ] += link.over_capacity_fixed_cost
                        overage_fixed_applied.add(lkey)

        storage_overage_qty_by_node = defaultdict(float)
        for key, data in events.items():
            if key.startswith("storage_overage:"):
                node_name = key.split(":", 1)[1]
                storage_overage_qty_by_node[node_name] += data.get("qty", 0) or 0

        for node in self.nodes_map.values():
            cost_cat_map = {
                "material": "material_storage",
                "factory": "factory_storage",
                "warehouse": "warehouse_storage",
                "store": "store_storage",
            }
            cat = cost_cat_map.get(node.node_type)
            if cat:
                pl["stock_costs"][f"{cat}_fixed"] += node.storage_cost_fixed
                for item, stock in self.stock[node.name].items():
                    pl["stock_costs"][
                        f"{cat}_variable"
                    ] += stock * node.storage_cost_variable.get(item, 0)
                over_qty = storage_overage_qty_by_node.get(node.name, 0)
                if over_qty > 0:
                    pl["stock_costs"][f"{cat}_variable"] += (
                        node.storage_over_capacity_variable_cost * over_qty
                    )
                    pl["stock_costs"][
                        f"{cat}_fixed"
                    ] += node.storage_over_capacity_fixed_cost

        # Penalties
        # Stockout cost: apply per node shortage units on the day
        for key, data in events.items():
            if ":" in key:
                continue
            try:
                node_name, _item = key.split("_", 1)
            except ValueError:
                continue
            shortage = data.get("shortage", 0) or 0
            if shortage > 0:
                node = self.nodes_map.get(node_name)
                if node:
                    pl["penalty_costs"]["stockout"] += (
                        getattr(node, "stockout_cost_per_unit", 0) * shortage
                    )

        # Backorder carrying cost per day
        supplier_bo_by_node = defaultdict(float)
        for future_day, records in self.pending_shipments.items():
            if future_day >= day + 1:
                for rec in records:
                    if len(rec) == 5:
                        _item, qty, supplier, _dest, is_bo = rec
                        if is_bo:
                            supplier_bo_by_node[supplier] += qty
        store_bo_by_node = defaultdict(float)
        for store_name, items in self.customer_backorders.items():
            store_bo_by_node[store_name] += sum(q for q in items.values() if q > 0)

        for node_name, qty in list(supplier_bo_by_node.items()) + list(
            store_bo_by_node.items()
        ):
            node = self.nodes_map.get(node_name)
            if node and qty > 0:
                pl["penalty_costs"]["backorder"] += (
                    getattr(node, "backorder_cost_per_unit_per_day", 0) * qty
                )

        total_flow = sum(pl["flow_costs"].values())
        total_stock = sum(pl["stock_costs"].values())
        total_penalty = sum(pl["penalty_costs"].values())
        pl["total_cost"] = (
            pl["material_cost"] + total_flow + total_stock + total_penalty
        )
        pl["profit_loss"] = pl["revenue"] - pl["total_cost"]
        self.daily_profit_loss.append(pl)
