import logging
import random
from collections import defaultdict
import math
from scipy.stats import norm
from typing import List, Dict, Any, Literal, Annotated, Union
from pydantic import BaseModel, Field
from copy import deepcopy # Added for deepcopy

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
    logging.FileHandler("simulation.log"),
    logging.StreamHandler()
])

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Data Models ---

class BomItem(BaseModel):
    item_name: str
    quantity_per: float = Field(gt=0)

class Product(BaseModel):
    name: str
    sales_price: float = Field(default=0, ge=0)
    assembly_bom: List[BomItem] = Field(default=[])

class NetworkLink(BaseModel):
    from_node: str
    to_node: str
    transportation_cost_fixed: float = Field(default=0, ge=0)
    transportation_cost_variable: float = Field(default=0, ge=0)

# --- Node Models (Discriminated Union) ---

class BaseNode(BaseModel):
    name: str
    initial_stock: Dict[str, float] = Field(default_factory=dict)
    lead_time: int = Field(default=1, ge=0)
    # Min-Max parameters removed
    storage_cost_fixed: float = Field(default=0, ge=0)
    storage_cost_variable: Dict[str, float] = Field(default_factory=dict)

class StoreNode(BaseNode):
    node_type: Literal["store"] = "store"
    service_level: float = Field(default=0.95, ge=0, le=1)

class WarehouseNode(BaseNode):
    node_type: Literal["warehouse"] = "warehouse"
    service_level: float = Field(default=0.95, ge=0, le=1)

class MaterialNode(BaseNode):
    node_type: Literal["material"] = "material"
    material_cost: Dict[str, float] = Field(default_factory=dict)

class FactoryNode(BaseNode):
    node_type: Literal["factory"] = "factory"
    producible_products: List[str]
    service_level: float = Field(default=0.95, ge=0, le=1) # Added for finished goods inventory management
    production_capacity: float = Field(default=float('inf'), gt=0)
    production_cost_fixed: float = Field(default=0, ge=0)
    production_cost_variable: float = Field(default=0, ge=0)
    # Fields for component replenishment policy
    reorder_point: Dict[str, float] = Field(default_factory=dict)
    order_up_to_level: Dict[str, float] = Field(default_factory=dict)
    moq: Dict[str, float] = Field(default_factory=dict)

AnyNode = Annotated[Union[StoreNode, WarehouseNode, MaterialNode, FactoryNode], Field(discriminator="node_type")]

class CustomerDemand(BaseModel):
    store_name: str
    product_name: str
    demand_mean: float = Field(ge=0)
    demand_std_dev: float = Field(ge=0)

class SimulationInput(BaseModel):
    planning_horizon: int = Field(gt=0)
    products: List[Product]
    nodes: List[AnyNode]
    network: List[NetworkLink]
    customer_demand: List[CustomerDemand]

# --- Simulation Engine ---

class SupplyChainSimulator:
    def __init__(self, sim_input: SimulationInput):
        self.input = sim_input
        self.products = {p.name: p for p in self.input.products}
        self.nodes_map = {n.name: n for n in self.input.nodes}
        self.network_map = {(link.from_node, link.to_node): link for link in self.input.network}
        
        self.stock = {n.name: defaultdict(float, n.initial_stock) for n in self.input.nodes}
        self.in_transit_orders = defaultdict(list)  # {arrival_day: [(item, qty, dest, from)]}
        self.production_orders = defaultdict(list) # {completion_day: [(item, qty, factory)]}
        self.order_history = defaultdict(list)  # {day: [(item, qty, from_node, to_node)]}

        self.cumulative_ordered = defaultdict(float)
        self.cumulative_received = defaultdict(float)

        self.daily_results = []
        self.daily_profit_loss = []
        self.node_order = self._get_topological_order()
        self.warehouse_demand_profiles = self._calculate_warehouse_demand_profiles()
        self.factory_demand_profiles = self._calculate_factory_demand_profiles()

    def _get_topological_order(self):
        order = []
        node_types = ['store', 'warehouse', 'factory', 'material']
        for n_type in node_types:
            for node in self.input.nodes:
                if node.node_type == n_type and node.name not in order:
                    order.append(node.name)
        return order

    def _calculate_warehouse_demand_profiles(self):
        profiles = defaultdict(lambda: defaultdict(lambda: {'mean': 0, 'variance': 0}))
        for wh in [n for n in self.input.nodes if n.node_type == 'warehouse']:
            for link in self.input.network:
                if link.from_node == wh.name and self.nodes_map[link.to_node].node_type == 'store':
                    store_name = link.to_node
                    for demand in self.input.customer_demand:
                        if demand.store_name == store_name:
                            profiles[wh.name][demand.product_name]['mean'] += demand.demand_mean
                            profiles[wh.name][demand.product_name]['variance'] += demand.demand_std_dev ** 2
        for _, products in profiles.items():
            for _, data in products.items(): data['std_dev'] = math.sqrt(data['variance'])
        return profiles

    def _calculate_factory_demand_profiles(self):
        profiles = defaultdict(lambda: defaultdict(lambda: {'mean': 0, 'variance': 0}))
        for factory in [n for n in self.input.nodes if n.node_type == 'factory']:
            for link in self.input.network:
                if link.from_node == factory.name and self.nodes_map[link.to_node].node_type == 'warehouse':
                    wh_name = link.to_node
                    wh_profile = self.warehouse_demand_profiles.get(wh_name, {})
                    for item, data in wh_profile.items():
                        if item in factory.producible_products:
                            profiles[factory.name][item]['mean'] += data['mean']
                            profiles[factory.name][item]['variance'] += data['variance']
        for _, products in profiles.items():
            for _, data in products.items(): data['std_dev'] = math.sqrt(data['variance'])
        return profiles

    def run(self):
        for day in range(self.input.planning_horizon):
            start_of_day_stock = {name: self.stock[name].copy() for name in self.nodes_map}
            daily_events = defaultdict(lambda: defaultdict(float))

            # 1. Receive incoming shipments and finished production orders
            logging.debug(f"--- Day {day}: Receiving Orders ---")
            received_orders_today = defaultdict(list) # New: To store orders received today
            in_transit_at_start_of_day = deepcopy(self.in_transit_orders) # For logging
            logging.debug(f"Day {day}: in_transit_orders at start of day: {self.in_transit_orders}")

            if day in self.in_transit_orders:
                for item, qty, dest_node_name, src_node_name in self.in_transit_orders[day]:
                    logging.debug(f"Day {day}: Receiving incoming shipment: Item {item}, Qty {qty}, Dest {dest_node_name}")
                    self.stock[dest_node_name][item] += qty
                    daily_events[f'{dest_node_name}_{item}']["incoming"] += qty
                    received_orders_today[dest_node_name].append((item, qty, src_node_name)) # New: Store received orders
                del self.in_transit_orders[day]
            logging.debug(f"Day {day}: in_transit_orders after receiving: {self.in_transit_orders}")
            for item, qty, factory_name in self.production_orders.pop(day, []):
                self.stock[factory_name][item] += qty
                daily_events[f'{factory_name}_{item}']["produced"] += qty

            # 2. Generate and fulfill customer demand
            logging.debug(f"--- Day {day}: Customer Demand ---")
            demand_signals = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
            for cd in self.input.customer_demand:
                demand_qty = max(0, round(random.gauss(cd.demand_mean, cd.demand_std_dev)))
                if demand_qty > 0:
                    store_name, item_name = cd.store_name, cd.product_name
                    logging.debug(f"Day {day}: Customer demand of {demand_qty} for {item_name} at {store_name}")
                    daily_events[f'{store_name}_{item_name}']["demand"] += demand_qty
                    available = self.stock[store_name].get(item_name, 0)
                    shipped = min(available, demand_qty)
                    if shipped > 0:
                        self.stock[store_name][item_name] -= shipped
                        daily_events[f'{store_name}_{item_name}']["sales"] += shipped
                        logging.debug(f"Day {day}: Shipped {shipped} of {item_name} to customer from {store_name}")
                    if demand_qty > shipped:
                        daily_events[f'{store_name}_{item_name}']["shortage"] += demand_qty - shipped
                        logging.debug(f"Day {day}: Shortage of {demand_qty - shipped} for {item_name} at {store_name}")

            # 3. Process nodes upstream (Store -> Warehouse -> Factory)
            logging.debug(f"--- Day {day}: Upstream Processing ---")

            # Aggregate demand from downstream nodes (orders received by them today)
            upstream_demand_signals = defaultdict(lambda: defaultdict(float))
            for dest_node_name, orders in received_orders_today.items():
                for item, qty, src_node_name in orders:
                    # If the order was placed by a downstream node to this upstream node
                    # and this upstream node is not a material node (material nodes don't fulfill orders this way)
                    if self.nodes_map[src_node_name].node_type != 'material': # src_node_name is the supplier here
                        upstream_demand_signals[src_node_name][item] += qty
            logging.debug(f"Day {day}: Aggregated upstream_demand_signals: {upstream_demand_signals}")

            for node_name in self.node_order:
                current_node = self.nodes_map[node_name]

                # --- FULFILLMENT (for upstream nodes) ---
                # Process demand from downstream nodes (orders placed by them)
                if node_name in upstream_demand_signals:
                    logging.debug(f"Day {day}: Fulfilling downstream demand for {node_name}")
                    for item_name, demand_qty in upstream_demand_signals[node_name].items():
                        logging.debug(f"Day {day}: Processing demand for {item_name} with qty {demand_qty} at {node_name}")
                        available = self.stock[node_name].get(item_name, 0)
                        shipped = min(available, demand_qty)
                        if shipped > 0:
                            self.stock[node_name][item_name] -= shipped
                            daily_events[f'{node_name}_{item_name}']["sales"] += shipped # Record as sales from upstream node
                            logging.debug(f"Day {day}: Shipped {shipped} of {item_name} from {node_name} to downstream")
                        if demand_qty > shipped:
                            daily_events[f'{node_name}_{item_name}']["shortage"] += demand_qty - shipped
                            logging.debug(f"Day {day}: Shortage of {demand_qty - shipped} for {item_name} at {node_name}")

                # Existing customer demand fulfillment (for store nodes)
                if node_name in demand_signals:
                    logging.debug(f"Day {day}: Fulfilling customer demand for {node_name}")
                    for item_name, requesters in demand_signals[node_name].items():
                        for requester_name, demand_qty in requesters.items():
                            logging.debug(f"Day {day}: Processing demand for {item_name} from {requester_name} with qty {demand_qty}")
                            logging.debug(f"Day {day}: Demand of {demand_qty} for {item_name} from {requester_name} to {node_name}")
                            # Record the demand for this node
                        
                        available = self.stock[node_name].get(item_name, 0)
                        shipped = min(available, demand_qty)
                        if shipped > 0:
                            self.stock[node_name][item_name] -= shipped
                            daily_events[f'{node_name}_{item_name}']["sales"] += shipped
                            self.cumulative_received[(requester_name, item_name)] += shipped
                            demand_signals[node_name][item_name][requester_name] -= shipped
                        if demand_qty > shipped:
                                daily_events[f'{node_name}_{item_name}']["shortage"] += demand_qty - shipped
                                logging.debug(f"Day {day}: Shortage of {demand_qty - shipped} for {item_name} at {node_name}")

                # --- REPLENISHMENT PLANNING ---
                items_to_manage = set(current_node.initial_stock.keys())
                # Stores & Warehouses use Service Level policy to order from upstream
                if isinstance(current_node, (StoreNode, WarehouseNode)):
                    logging.debug(f"Day {day}: Replenishment planning for {node_name}")
                    for item_name in items_to_manage:
                        parent_name = next((l.from_node for l in self.input.network if l.to_node == node_name), None)
                        if not parent_name: continue
                        replenishment_lt = current_node.lead_time

                        profile = self.warehouse_demand_profiles.get(node_name, {}).get(item_name) if isinstance(current_node, WarehouseNode) else next((d for d in self.input.customer_demand if d.store_name == node_name and d.product_name == item_name), None)
                        if not profile: continue
                        demand_mean = profile['mean'] if isinstance(profile, dict) else profile.demand_mean
                        demand_std = profile['std_dev'] if isinstance(profile, dict) else profile.demand_std_dev

                        inv_on_hand = self.stock[node_name].get(item_name, 0)
                        inv_in_transit = sum(
                            qty for orders in self.in_transit_orders.values()
                            for item, qty, dest, _ in orders
                            if dest == node_name and item == item_name
                        )
                        inv_pos = inv_on_hand + inv_in_transit
                        order_up_to = norm.ppf(current_node.service_level) * demand_std * math.sqrt(replenishment_lt) + demand_mean * (replenishment_lt + 1)
                        qty_to_order = max(0, math.ceil(order_up_to - inv_pos))
                        logging.debug(f"Day {day}: Node {node_name}, Item {item_name}: inv_pos={inv_pos}, order_up_to={order_up_to}, calculated qty_to_order={qty_to_order}")

                        if qty_to_order > 0:
                            logging.debug(f"Day {day}: Replenishment order of {qty_to_order} for {item_name} from {node_name} to {parent_name}. Placing order via _place_order.")
                            self._place_order(parent_name, node_name, item_name, qty_to_order, day)
                
                # Factories use Service Level for finished goods, Min-Max for components
                if isinstance(current_node, FactoryNode):
                    # Plan finished goods production
                    logging.debug(f"Day {day}: Production planning for {node_name}")
                    for item_name in current_node.producible_products:
                        profile = self.factory_demand_profiles.get(node_name, {}).get(item_name)
                        if not profile: continue
                        inv_pos = self.stock[node_name].get(item_name, 0) + sum(q for i,q,f in self.production_orders.get(day, []) if f==node_name and i==item_name)
                        order_up_to = norm.ppf(current_node.service_level) * profile['std_dev'] * math.sqrt(current_node.lead_time) + profile['mean'] * (current_node.lead_time + 1)
                        production_needed = max(0, math.ceil(order_up_to - inv_pos))
                        producible_qty = min(production_needed, current_node.production_capacity)
                        if producible_qty > 0:
                            components_ok = all(self.stock[node_name].get(bom.item_name, 0) >= bom.quantity_per * producible_qty for bom in self.products[item_name].assembly_bom)
                            if components_ok:
                                logging.debug(f"Day {day}: Production order of {producible_qty} for {item_name} at {node_name}")
                                for bom in self.products[item_name].assembly_bom:
                                    consumed = bom.quantity_per * producible_qty
                                    self.stock[node_name][bom.item_name] -= consumed
                                    daily_events[f'{node_name}_{bom.item_name}']["consumption"] += consumed
                                self.production_orders[day + current_node.lead_time].append((item_name, producible_qty, node_name))
                    
                    # Order components
                    logging.debug(f"Day {day}: Component ordering for {node_name}")
                    for item_name in {c.item_name for p in current_node.producible_products for c in self.products[p].assembly_bom}:
                        reorder_point = current_node.reorder_point.get(item_name)
                        if reorder_point is None: continue
                        inv_on_hand = self.stock[node_name].get(item_name, 0)
                        inv_in_transit = sum(
                            qty for orders in self.in_transit_orders.values()
                            for item, qty, dest, _ in orders
                            if dest == node_name and item == item_name
                        )
                        inv_pos = inv_on_hand + inv_in_transit
                        if inv_pos <= reorder_point:
                            order_up_to = current_node.order_up_to_level.get(item_name, inv_pos)
                            qty_to_order = max(0, order_up_to - inv_pos)
                            moq = current_node.moq.get(item_name, 0)
                            if 0 < qty_to_order < moq: qty_to_order = moq
                            if qty_to_order > 0:
                                parent_name = next((l.from_node for l in self.input.network if l.to_node == node_name and self.nodes_map[l.from_node].node_type == 'material' and item_name in self.nodes_map[l.from_node].material_cost), None)
                                if parent_name:
                                    logging.debug(f"Day {day}: Component order of {qty_to_order} for {item_name} from {node_name} to {parent_name}. Placing order via _place_order.")
                                    self._place_order(parent_name, node_name, item_name, qty_to_order, day)
                                    logging.debug(f"Day {day}: Node {node_name}, Item {item_name}: inv_pos={inv_pos}, order_up_to={order_up_to}, moq={moq}, calculated qty_to_order={qty_to_order}")

            # 4. Record daily snapshot
            self.record_daily_snapshot(day, start_of_day_stock, self.stock, daily_events)
            self.calculate_daily_profit_loss(day, daily_events)

        return self.daily_results, self.daily_profit_loss


    def _place_order(self, supplier_node_name: str, customer_node_name: str, item_name: str, quantity: float, current_day: int):
        customer_node = self.nodes_map[customer_node_name]
        arrival_day = current_day + customer_node.lead_time
        logging.debug(f"DEBUG: Day {current_day}: Placing order for {item_name} qty {quantity} from {supplier_node_name} to {customer_node_name}. Customer lead time (used for arrival): {customer_node.lead_time}. Expected arrival day: {arrival_day}")
        self.in_transit_orders[arrival_day].append((item_name, quantity, customer_node_name, supplier_node_name))
        self.order_history[current_day].append((item_name, quantity, supplier_node_name, customer_node_name))
        self.cumulative_ordered[(customer_node_name, item_name)] += quantity
        import traceback
        logging.debug(f"DEBUG: Call stack for _place_order: {''.join(traceback.format_stack())}")
        

    def record_daily_snapshot(self, day, start_stock, end_stock, events):
        snapshot = {"day": day + 1, "nodes": {}}
        all_node_names = set(start_stock.keys()) | set(end_stock.keys())

        # Calculate ordered quantities from order_history for the current day
        daily_ordered_quantities = defaultdict(lambda: defaultdict(float))
        for item, qty, _, dest in self.order_history.get(day, []):
            if dest in self.nodes_map:
                daily_ordered_quantities[dest][item] += qty

        for name in sorted(list(all_node_names)):
            node_snapshot = {}
            all_items = set(start_stock.get(name, {}).keys()) | set(end_stock.get(name, {}).keys())
            
            for item in sorted(list(all_items)):
                event_key = f'{name}_{item}'
                item_snapshot = events.get(event_key, defaultdict(float))
                
                item_snapshot["start_stock"] = start_stock.get(name, {}).get(item, 0)
                item_snapshot["end_stock"] = end_stock.get(name, {}).get(item, 0)
                
                # Add ordered_quantity from the accumulated daily_ordered_quantities
                item_snapshot["ordered_quantity"] = daily_ordered_quantities[name][item]

                # Ensure all metrics are present, defaulting to 0
                for metric in ['incoming', 'demand', 'sales', 'consumption', 'produced', 'shortage']: # removed 'ordered_quantity' as it's now calculated
                    if metric not in item_snapshot:
                        item_snapshot[metric] = 0

                node_snapshot[item] = item_snapshot

            if node_snapshot: # Only add node if it has item data
                snapshot["nodes"][name] = node_snapshot
        
        self.daily_results.append(snapshot)

    def calculate_daily_profit_loss(self, day, events):
        pl = {
            "day": day + 1,
            "revenue": 0,
            "material_cost": 0,
            "flow_costs": {
                "material_transport_fixed": 0, "material_transport_variable": 0,
                "production_fixed": 0, "production_variable": 0,
                "warehouse_transport_fixed": 0, "warehouse_transport_variable": 0,
                "store_transport_fixed": 0, "store_transport_variable": 0,
            },
            "stock_costs": {
                "material_storage_fixed": 0, "material_storage_variable": 0,
                "factory_storage_fixed": 0, "factory_storage_variable": 0,
                "warehouse_storage_fixed": 0, "warehouse_storage_variable": 0,
                "store_storage_fixed": 0, "store_storage_variable": 0,
            },
            "total_cost": 0,
            "profit_loss": 0
        }

        # Revenue
        for key, data in events.items():
            if 'sales' in data:
                node_name, item_name = key.split('_', 1)
                if self.nodes_map[node_name].node_type == 'store':
                    pl["revenue"] += data['sales'] * self.products[item_name].sales_price

        # Flow Costs
        nodes_produced = set()
        
        # Track transportation costs by link type
        transport_costs_by_type = defaultdict(lambda: defaultdict(float))
        links_with_fixed_cost_applied = set() # To ensure fixed cost is applied only once per link per day

        for key, data in events.items():
            node_name, item_name = key.split('_', 1)
            node = self.nodes_map[node_name]
            
            if 'ordered_quantity' in data and 'ordered_from' in data:
                supplier_name = data['ordered_from']
                supplier = self.nodes_map.get(supplier_name)
                link_key = (supplier_name, node_name)
                link = self.network_map.get(link_key)
                qty = data['ordered_quantity']

                if link:
                    # Material Cost (only if supplier is a MaterialNode)
                    if isinstance(supplier, MaterialNode):
                        pl["material_cost"] += supplier.material_cost.get(item_name, 0) * qty

                    # Apply fixed transportation cost only once per link per day
                    if link_key not in links_with_fixed_cost_applied:
                        if isinstance(supplier, MaterialNode) and isinstance(node, FactoryNode):
                            transport_costs_by_type["material_transport"]["fixed"] += link.transportation_cost_fixed
                        elif isinstance(supplier, FactoryNode) and isinstance(node, WarehouseNode):
                            transport_costs_by_type["warehouse_transport"]["fixed"] += link.transportation_cost_fixed
                        elif isinstance(supplier, WarehouseNode) and isinstance(node, StoreNode):
                            transport_costs_by_type["store_transport"]["fixed"] += link.transportation_cost_fixed
                        links_with_fixed_cost_applied.add(link_key)

                    # Accumulate variable transportation cost
                    if isinstance(supplier, MaterialNode) and isinstance(node, FactoryNode):
                        transport_costs_by_type["material_transport"]["variable"] += link.transportation_cost_variable * qty
                    elif isinstance(supplier, FactoryNode) and isinstance(node, WarehouseNode):
                        transport_costs_by_type["warehouse_transport"]["variable"] += link.transportation_cost_variable * qty
                    elif isinstance(supplier, WarehouseNode) and isinstance(node, StoreNode):
                        transport_costs_by_type["store_transport"]["variable"] += link.transportation_cost_variable * qty
                    # Add other transport types as needed (e.g., Factory to Store, Warehouse to Factory)

            if 'produced' in data and isinstance(node, FactoryNode):
                pl["flow_costs"]["production_variable"] += node.production_cost_variable * data['produced']
                nodes_produced.add(node_name)
        
        # Add fixed production costs
        for node_name in nodes_produced:
            pl["flow_costs"]["production_fixed"] += self.nodes_map[node_name].production_cost_fixed

        # Consolidate transportation costs
        for transport_type, costs in transport_costs_by_type.items():
            pl["flow_costs"][f"{transport_type}_fixed"] = costs["fixed"]
            pl["flow_costs"][f"{transport_type}_variable"] = costs["variable"]

        # Stock Costs
        for node in self.nodes_map.values():
            cost_cat_map = {
                "material": "material_storage",
                "factory": "factory_storage",
                "warehouse": "warehouse_storage",
                "store": "store_storage"
            }
            cat = cost_cat_map.get(node.node_type)
            if cat:
                pl["stock_costs"][f"{cat}_fixed"] += node.storage_cost_fixed
                for item, stock in self.stock[node.name].items():
                    pl["stock_costs"][f"{cat}_variable"] += stock * node.storage_cost_variable.get(item, 0)

        # Final Calculation
        total_flow = sum(pl["flow_costs"].values())
        total_stock = sum(pl["stock_costs"].values())
        pl["total_cost"] = pl["material_cost"] + total_flow + total_stock
        pl["profit_loss"] = pl["revenue"] - pl["total_cost"]
        self.daily_profit_loss.append(pl)

# --- API Endpoint ---

@app.post("/simulation")
async def run_simulation(input_data: SimulationInput):
    try:
        logging.info(f"Received input data: {input_data.json()}")
        simulator = SupplyChainSimulator(input_data)
        results, profit_loss = simulator.run()
        logging.info(f"Calculated profit_loss: {profit_loss}")
        return {
            "message": "Simulation completed successfully.",
            "results": results,
            "profit_loss": profit_loss
        }
    except Exception as e:
        import traceback
        logging.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@app.get("/", response_class=HTMLResponse)
async def read_index():
    try:
        with open("index.html") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>Error</h1><p>index.html not found.</p>", status_code=404)

if __name__ == "__main__":
    import json
    import logging

    # Configure logging to output DEBUG messages to simulation.log
    logging.basicConfig(level=logging.DEBUG, filename='simulation.log', filemode='w', format='%(asctime)s - %(levelname)s - %(message)s')
    print("--- Script started ---")

    # Load the sample input from the JS file to ensure consistency
    with open("static/js/main.js") as f:
        js_content = f.read()
        # A bit of a hack to find the JSON blob inside the script tag
        json_str = js_content.split('const sampleInput = ')[1].split(';')[0]
    
    sim_input_dict = json.loads(json_str)
    sim_input = SimulationInput(**sim_input_dict)
    
    simulator = SupplyChainSimulator(sim_input)
    results, profit_loss = simulator.run() 
    
    logging.info("--- SIMULATION TEST COMPLETE ---")
    logging.info("--- PROFIT/LOSS DATA ---")
    for day_pl in profit_loss:
        logging.info(day_pl)

    # Check if transportation costs were generated
    in_transit_at_end = defaultdict(float)
    for arrival_day, orders in simulator.in_transit_orders.items():
        for item, qty, dest, _ in orders:
            in_transit_at_end[(dest, item)] += qty

    logging.info("CUMULATIVE ORDERED:")
    logging.info(simulator.cumulative_ordered)
    logging.info("CUMULATIVE RECEIVED:")
    logging.info(simulator.cumulative_received)
    logging.info("IN TRANSIT AT END:")
    logging.info(in_transit_at_end)

    validation_passed = True
    all_keys = set(simulator.cumulative_ordered.keys()) | set(simulator.cumulative_received.keys())

    for key in all_keys:
        ordered = simulator.cumulative_ordered.get(key, 0)
        received = simulator.cumulative_received.get(key, 0)
        in_transit = in_transit_at_end.get(key, 0)
        
        # Using a small tolerance for float comparison
        if not math.isclose(ordered, received + in_transit, rel_tol=1e-9, abs_tol=1e-9):
            validation_passed = False
            logging.error(f"VALIDATION FAILED for {key}: Ordered={ordered}, Received={received}, InTransit={in_transit}")

    if validation_passed:
        logging.info("*** VALIDATION SUCCESS: Cumulative Ordered == Cumulative Received + In-Transit at End ***")
    else:
        logging.info("*** VALIDATION FAILURE ***")
