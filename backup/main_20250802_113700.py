from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import random
from typing import List, Dict, Union
from collections import defaultdict
import math

app = FastAPI()

# --- Data Models ---


class BomItem(BaseModel):
    item_name: str
    quantity_per: float = Field(gt=0)


class Product(BaseModel):
    name: str
    assembly_bom: List[BomItem] = Field(default=[])


class Node(BaseModel):
    name: str
    node_type: str
    initial_stock: Dict[str, float] = Field(default_factory=dict)
    lead_time: int = Field(default=1, ge=0)
    # New: Ordering policy parameters
    reorder_point: Dict[str, float] = Field(
        default_factory=dict
    )  # {item_name: quantity}
    order_up_to_level: Dict[str, float] = Field(
        default_factory=dict
    )  # {item_name: quantity}
    moq: Dict[str, float] = Field(default_factory=dict)  # {item_name: quantity}


class FactoryNode(Node):
    node_type: str = "factory"
    producible_products: List[str]
    production_capacity: float = Field(default=float("inf"), gt=0)  # Max units per day


class CustomerDemand(BaseModel):
    store_name: str
    product_name: str
    demand_mean: float = Field(ge=0)
    demand_std_dev: float = Field(ge=0)


class SimulationInput(BaseModel):
    planning_horizon: int = Field(gt=0)
    products: List[Product]
    nodes: List[Union[FactoryNode, Node]]
    network: Dict[str, Union[str, List[str]]]
    customer_demand: List[CustomerDemand]


# --- Simulation Engine ---


class SupplyChainSimulator:
    def __init__(self, sim_input: SimulationInput):
        self.input = sim_input
        self.products = {p.name: p for p in self.input.products}
        self.nodes_map = {n.name: n for n in self.input.nodes}

        self.stock = {
            n.name: defaultdict(float, n.initial_stock) for n in self.input.nodes
        }
        self.in_transit_orders = defaultdict(
            list
        )  # {arrival_day: [(item_name, quantity, destination_node)]}
        self.daily_results = []
        self.node_order = self._get_topological_order()

    def _get_topological_order(self):
        order = []
        node_types = ["store", "warehouse", "factory", "material"]
        for n_type in node_types:
            for node in self.input.nodes:
                if node.node_type == n_type and node.name not in order:
                    order.append(node.name)
        return order

    def run(self):
        for day in range(self.input.planning_horizon):
            daily_demand_from_children = defaultdict(
                lambda: defaultdict(float)
            )  # Demand passed up from children
            daily_events = defaultdict(lambda: defaultdict(float))
            start_of_day_stock = {
                name: self.stock[name].copy() for name in self.nodes_map
            }

            # 1. Fulfill arriving orders
            for item_name, quantity, dest_node_name in self.in_transit_orders.pop(
                day, []
            ):
                self.stock[dest_node_name][item_name] += quantity
                daily_events[f"{dest_node_name}_{item_name}"]["incoming"] += quantity

            # 2. Generate initial customer demand for stores
            for demand_event in self.input.customer_demand:
                demand_qty = max(
                    0,
                    round(
                        random.gauss(
                            demand_event.demand_mean, demand_event.demand_std_dev
                        )
                    ),
                )
                daily_demand_from_children[demand_event.store_name][
                    demand_event.product_name
                ] += demand_qty

            # 3. Process nodes from downstream to upstream for fulfillment and order generation
            # This loop processes demand and generates replenishment orders
            for node_name in self.node_order:
                current_node = self.nodes_map[node_name]

                # Get all items that had demand or were produced/consumed by this node today
                # This is a simplified way to get items to process for the day
                items_to_process = set(
                    daily_demand_from_children[node_name].keys()
                ) | set(self.stock[node_name].keys())

                for item_name in list(items_to_process):
                    # --- Demand Fulfillment ---
                    demand_qty = daily_demand_from_children[node_name].get(item_name, 0)

                    if demand_qty > 0:
                        daily_events[f"{node_name}_{item_name}"][
                            "demand"
                        ] += demand_qty  # ADDED THIS LINE
                        available_stock = self.stock[node_name].get(item_name, 0)
                        fulfilled_qty = min(available_stock, demand_qty)
                        shortage_qty = demand_qty - fulfilled_qty

                        if fulfilled_qty > 0:
                            self.stock[node_name][item_name] -= fulfilled_qty
                            daily_events[f"{node_name}_{item_name}"][
                                "sales"
                            ] += fulfilled_qty

                        if shortage_qty > 0:
                            daily_events[f"{node_name}_{item_name}"][
                                "shortage"
                            ] += shortage_qty

                    # --- Production (for Factory Nodes) ---
                    if (
                        isinstance(current_node, FactoryNode)
                        and item_name in current_node.producible_products
                    ):
                        product_def = self.products.get(item_name)
                        if product_def:
                            # Calculate how much to produce: cover demand + replenish to target level
                            current_inventory_position = self.stock[node_name].get(
                                item_name, 0
                            )
                            for arrival_day, orders in self.in_transit_orders.items():
                                for (
                                    order_item_name,
                                    order_qty,
                                    dest_node_name,
                                ) in orders:
                                    if (
                                        dest_node_name == node_name
                                        and order_item_name == item_name
                                    ):
                                        current_inventory_position += order_qty

                            production_needed_for_replenishment = 0
                            target_level = current_node.order_up_to_level.get(
                                item_name, 0
                            )
                            if (
                                target_level > 0
                                and current_inventory_position < target_level
                            ):
                                production_needed_for_replenishment = (
                                    target_level - current_inventory_position
                                )

                            # Total production target: demand + replenishment needed
                            production_target = (
                                demand_qty + production_needed_for_replenishment
                            )

                            can_produce = min(
                                production_target, current_node.production_capacity
                            )

                            # Check if components are available for production
                            components_available = True
                            for bom_item in product_def.assembly_bom:
                                if (
                                    self.stock[node_name].get(bom_item.item_name, 0)
                                    < bom_item.quantity_per * can_produce
                                ):
                                    components_available = False
                                    break

                            if components_available and can_produce > 0:
                                # Consume components
                                for bom_item in product_def.assembly_bom:
                                    consumed_qty = bom_item.quantity_per * can_produce
                                    self.stock[node_name][
                                        bom_item.item_name
                                    ] -= consumed_qty
                                    daily_events[f"{node_name}_{bom_item.item_name}"][
                                        "consumption"
                                    ] += consumed_qty

                                # Add produced item to stock
                                self.stock[node_name][item_name] += can_produce
                                daily_events[f"{node_name}_{item_name}"][
                                    "produced"
                                ] += can_produce

                    # --- Order Placement (Replenishment) ---
                    # Calculate current inventory position (stock + in-transit)
                    current_inventory_position = self.stock[node_name].get(item_name, 0)
                    for arrival_day, orders in self.in_transit_orders.items():
                        for order_item_name, order_qty, dest_node_name in orders:
                            if (
                                dest_node_name == node_name
                                and order_item_name == item_name
                            ):
                                current_inventory_position += order_qty

                    qty_to_order = 0
                    reorder_point = current_node.reorder_point.get(
                        item_name, -1
                    )  # -1 means no reorder point
                    order_up_to_level = current_node.order_up_to_level.get(
                        item_name, -1
                    )  # -1 means no order up to level

                    if (
                        reorder_point != -1
                        and current_inventory_position <= reorder_point
                    ):
                        if order_up_to_level != -1:
                            needed = order_up_to_level - current_inventory_position
                            if needed > 0:
                                moq = current_node.moq.get(item_name, 1)
                                qty_to_order = math.ceil(needed / moq) * moq
                        else:  # If no order_up_to_level, just order a fixed quantity (e.g., 1 unit or a default)
                            qty_to_order = current_node.moq.get(
                                item_name, 1
                            )  # Use MOQ as fixed order quantity if no S

                    if qty_to_order > 0:
                        parent_node_names = self.input.network.get(node_name)
                        if parent_node_names:
                            if isinstance(parent_node_names, str):
                                parent_node_names = [parent_node_names]

                            # Find a parent that supplies this item
                            supplier_found = False
                            for parent_name in parent_node_names:
                                # Check if the parent node has this item in its initial stock (simplified supplier check)
                                if item_name in self.nodes_map[
                                    parent_name
                                ].initial_stock or (
                                    isinstance(self.nodes_map[parent_name], FactoryNode)
                                    and item_name
                                    in self.nodes_map[parent_name].producible_products
                                ):

                                    # Pass demand upstream to the parent
                                    daily_demand_from_children[parent_name][
                                        item_name
                                    ] += qty_to_order
                                    self._place_order(
                                        parent_name,
                                        node_name,
                                        item_name,
                                        qty_to_order,
                                        day,
                                        daily_events,
                                    )
                                    supplier_found = True
                                    break  # Assume one supplier for now
                            # If no supplier found, the order is lost (or backlogged, not implemented yet)
                            if not supplier_found:
                                daily_events[f"{node_name}_{item_name}"][
                                    "lost_order"
                                ] += qty_to_order

            # 4. Record daily snapshot
            self.record_daily_snapshot(day, start_of_day_stock, daily_events)

        return self.daily_results

    def _place_order(
        self,
        supplier_node_name: str,
        customer_node_name: str,
        item_name: str,
        quantity: float,
        current_day: int,
        daily_events: defaultdict,
    ):
        supplier_node = self.nodes_map[supplier_node_name]
        arrival_day = current_day + supplier_node.lead_time
        self.in_transit_orders[arrival_day].append(
            (item_name, quantity, customer_node_name)
        )
        daily_events[f"{customer_node_name}_{item_name}"][
            "ordered_quantity"
        ] += quantity

    def record_daily_snapshot(self, day, start_stock, events):
        snapshot = {"day": day + 1, "nodes": {}}
        for name, node in self.nodes_map.items():
            node_snapshot = {}
            all_items = set(start_stock[name].keys()) | set(self.stock[name].keys())
            for item in sorted(list(all_items)):
                event_key = f"{name}_{item}"
                node_snapshot[item] = {
                    "start_stock": start_stock[name].get(item, 0),
                    "incoming": events[event_key].get("incoming", 0),
                    "demand": events[event_key].get("demand", 0),
                    "sales": events[event_key].get("sales", 0),
                    "consumption": events[event_key].get("consumption", 0),
                    "produced": events[event_key].get("produced", 0),
                    "shortage": events[event_key].get("shortage", 0),
                    "end_stock": self.stock[name].get(item, 0),
                    "ordered_quantity": events[event_key].get("ordered_quantity", 0),
                }
            snapshot["nodes"][name] = node_snapshot
        self.daily_results.append(snapshot)


# --- API Endpoint ---


@app.post("/simulation")
async def run_simulation(input_data: SimulationInput):
    try:
        simulator = SupplyChainSimulator(input_data)
        results = simulator.run()
        return {"message": "Simulation completed successfully.", "results": results}
    except Exception as e:
        import traceback

        print(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail=f"An unexpected error occurred: {str(e)}"
        )


@app.get("/", response_class=HTMLResponse)
async def read_index():
    try:
        with open("index.html") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse(
            "<h1>Error</h1><p>index.html not found.</p>", status_code=404
        )
