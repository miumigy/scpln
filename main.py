import logging
import random
from collections import defaultdict
import math
# Normal quantile function with fallback to Python stdlib if SciPy unavailable
try:
    from scipy.stats import norm as _scipy_norm  # type: ignore
    norm_ppf = _scipy_norm.ppf
except Exception:  # pragma: no cover
    from statistics import NormalDist
    norm_ppf = NormalDist().inv_cdf
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
    lead_time: int = Field(default=0, ge=0)
    # Capacity (per day) and over-capacity policy/costs for this link
    capacity_per_day: float = Field(default=float('inf'), gt=0)
    allow_over_capacity: bool = Field(default=True)
    over_capacity_fixed_cost: float = Field(default=0, ge=0)
    over_capacity_variable_cost: float = Field(default=0, ge=0)
    # Optional per-item MOQ and order multiple for this link
    moq: Dict[str, float] = Field(default_factory=dict)
    order_multiple: Dict[str, float] = Field(default_factory=dict)

# --- Node Models (Discriminated Union) ---

class BaseNode(BaseModel):
    name: str
    initial_stock: Dict[str, float] = Field(default_factory=dict)
    lead_time: int = Field(default=1, ge=0)
    # Min-Max parameters removed
    storage_cost_fixed: float = Field(default=0, ge=0)
    storage_cost_variable: Dict[str, float] = Field(default_factory=dict)
    # Whether this node backorders unmet outbound demand (carry to future days)
    backorder_enabled: bool = Field(default=True)
    # Storage capacity (total units across items) and over-capacity policy/costs
    storage_capacity: float = Field(default=float('inf'), gt=0)
    allow_storage_over_capacity: bool = Field(default=True)
    storage_over_capacity_fixed_cost: float = Field(default=0, ge=0)
    storage_over_capacity_variable_cost: float = Field(default=0, ge=0)

class StoreNode(BaseNode):
    node_type: Literal["store"] = "store"
    service_level: float = Field(default=0.95, ge=0, le=1)
    backorder_enabled: bool = Field(default=True)
    # Optional per-item MOQ and order multiple for replenishment from upstream
    moq: Dict[str, float] = Field(default_factory=dict)
    order_multiple: Dict[str, float] = Field(default_factory=dict)

class WarehouseNode(BaseNode):
    node_type: Literal["warehouse"] = "warehouse"
    service_level: float = Field(default=0.95, ge=0, le=1)
    # Optional per-item MOQ and order multiple for replenishment from upstream
    moq: Dict[str, float] = Field(default_factory=dict)
    order_multiple: Dict[str, float] = Field(default_factory=dict)

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
    # Production over-capacity policy/costs
    allow_production_over_capacity: bool = Field(default=True)
    production_over_capacity_fixed_cost: float = Field(default=0, ge=0)
    production_over_capacity_variable_cost: float = Field(default=0, ge=0)
    # Fields for component replenishment policy
    reorder_point: Dict[str, float] = Field(default_factory=dict)
    order_up_to_level: Dict[str, float] = Field(default_factory=dict)
    moq: Dict[str, float] = Field(default_factory=dict)
    # Optional per-item order multiple for components (e.g., case pack size)
    order_multiple: Dict[str, float] = Field(default_factory=dict)

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
        # Pending outbound shipments scheduled by ship day. Each entry:
        #   (item_name, qty, supplier_node_name, dest_node_name, is_backorder)
        self.pending_shipments = defaultdict(list)  # {ship_day: [tuple]}
        # Customer backorders at store level: {store_name: {item_name: qty}}
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

            # 1-a. Process scheduled shipments that are due to ship today (arrive same day)
            if day in self.pending_shipments:
                shipped_so_far = defaultdict(float)  # per link per day
                dest_incoming_today = defaultdict(float)  # per destination node per day (for storage capacity)
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

                    # Link capacity enforcement
                    link_cap = getattr(link_obj, 'capacity_per_day', float('inf')) if link_obj else float('inf')
                    link_allow_over = getattr(link_obj, 'allow_over_capacity', True) if link_obj else True
                    remaining_link_cap = max(0.0, link_cap - shipped_so_far[(supplier_name, dest_name)])

                    shipped_candidate = request_qty
                    link_over_qty = 0.0
                    if not link_allow_over:
                        shipped_candidate = min(shipped_candidate, remaining_link_cap)
                    else:
                        if remaining_link_cap < shipped_candidate:
                            link_over_qty = shipped_candidate - remaining_link_cap

                    # Destination storage capacity enforcement
                    storage_cap = getattr(dest_node, 'storage_capacity', float('inf'))
                    storage_allow_over = getattr(dest_node, 'allow_storage_over_capacity', True)
                    total_stock_now = sum(self.stock[dest_name].values())
                    remaining_storage = max(0.0, storage_cap - (total_stock_now + dest_incoming_today[dest_name]))
                    storage_over_add = 0.0
                    if not storage_allow_over:
                        shipped_candidate = min(shipped_candidate, remaining_storage)

                    # Now ship the candidate amount
                    shipped = max(0.0, min(request_qty, shipped_candidate))

                    # Supplier faces demand today
                    daily_events[f'{supplier_name}_{item}']["demand"] += qty
                    if shipped > 0:
                        self.stock[supplier_name][item] -= shipped
                        daily_events[f'{supplier_name}_{item}']["sales"] += shipped

                        # Update shipped counters
                        shipped_so_far[(supplier_name, dest_name)] += shipped
                        dest_incoming_today[dest_name] += shipped

                        # Storage over-capacity amount added by this receipt (if allowed)
                        if storage_allow_over and storage_cap != float('inf'):
                            before_over = max(0.0, (total_stock_now + dest_incoming_today[dest_name] - shipped) - storage_cap)
                            after_over = max(0.0, (total_stock_now + dest_incoming_today[dest_name]) - storage_cap)
                            storage_over_add = max(0.0, after_over - before_over)
                            if storage_over_add > 0:
                                skey = f'storage_overage:{dest_name}'
                                if skey not in daily_events:
                                    daily_events[skey] = {"qty": 0.0}
                                daily_events[skey]["qty"] += storage_over_add

                        # Deliver to destination immediately (arrival after lead time elapsed)
                        self.stock[dest_name][item] += shipped
                        daily_events[f'{dest_name}_{item}']["incoming"] += shipped
                        # Record transport event (for flow cost calculation)
                        tkey = f'transport:{supplier_name}->{dest_name}:{item}'
                        if tkey not in daily_events:
                            daily_events[tkey] = {"qty": 0.0}
                        daily_events[tkey]["qty"] += shipped

                        # Record link over-capacity used (if allowed)
                        if link_allow_over and link_cap != float('inf'):
                            before_over_link = max(0.0, (shipped_so_far[(supplier_name, dest_name)] - shipped) - link_cap)
                            after_over_link = max(0.0, shipped_so_far[(supplier_name, dest_name)] - link_cap)
                            over_added = max(0.0, after_over_link - before_over_link)
                            if over_added > 0:
                                okey = f'transport_overage:{supplier_name}->{dest_name}'
                                if okey not in daily_events:
                                    daily_events[okey] = {"qty": 0.0}
                                daily_events[okey]["qty"] += over_added

                    if qty > shipped:
                        shortage = qty - shipped
                        daily_events[f'{supplier_name}_{item}']["shortage"] += shortage
                        logging.debug(f"Day {day}: Supplier {supplier_name} shortage {shortage} of {item} for {dest_name}")
                        # If supplier is configured to backorder, reschedule the remaining qty to the next day
                        if getattr(supplier_node, 'backorder_enabled', True):
                            self.pending_shipments[day + 1].append((item, shortage, supplier_name, dest_name, True))

            if day in self.in_transit_orders:
                for item, qty, dest_node_name, src_node_name in self.in_transit_orders[day]:
                    logging.debug(f"Day {day}: Receiving incoming shipment: Item {item}, Qty {qty}, Dest {dest_node_name}")
                    self.stock[dest_node_name][item] += qty
                    daily_events[f'{dest_node_name}_{item}']["incoming"] += qty
                    received_orders_today[dest_node_name].append((item, qty, src_node_name)) # New: Store received orders
                del self.in_transit_orders[day]
            logging.debug(f"Day {day}: in_transit_orders after receiving: {self.in_transit_orders}")
            for item, qty, factory_name in self.production_orders.pop(day, []):
                # Enforce factory storage capacity when receiving finished goods
                factory_node = self.nodes_map[factory_name]
                storage_cap = getattr(factory_node, 'storage_capacity', float('inf'))
                allow_over = getattr(factory_node, 'allow_storage_over_capacity', True)
                total_stock_now = sum(self.stock[factory_name].values())
                remaining_storage = max(0.0, storage_cap - total_stock_now)
                to_store = qty
                if not allow_over:
                    to_store = min(qty, remaining_storage)
                if to_store > 0:
                    self.stock[factory_name][item] += to_store
                    daily_events[f'{factory_name}_{item}']["produced"] += to_store
                    # Record overage amount if any (allowed)
                    if allow_over and storage_cap != float('inf'):
                        over_after = max(0.0, (total_stock_now + to_store) - storage_cap)
                        over_before = max(0.0, total_stock_now - storage_cap)
                        over_add = max(0.0, over_after - over_before)
                        if over_add > 0:
                            skey = f'storage_overage:{factory_name}'
                            if skey not in daily_events:
                                daily_events[skey] = {"qty": 0.0}
                            daily_events[skey]["qty"] += over_add
                # If not all could be stored and over-capacity is not allowed, delay to next day
                if to_store < qty and not allow_over:
                    remaining = qty - to_store
                    self.production_orders[day + 1].append((item, remaining, factory_name))

            # 1-b. Fulfill customer backorders at stores immediately after receipts
            for node in self.input.nodes:
                if node.node_type == 'store':
                    store = node.name
                    for item_name, bo_qty in list(self.customer_backorders[store].items()):
                        if bo_qty <= 0:
                            continue
                        available = self.stock[store].get(item_name, 0)
                        shipped = min(available, bo_qty)
                        if shipped > 0:
                            self.stock[store][item_name] -= shipped
                            self.customer_backorders[store][item_name] -= shipped
                            daily_events[f'{store}_{item_name}']["sales"] += shipped

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
                        # If store supports backorder, accumulate customer backorders
                        node_obj = self.nodes_map.get(store_name)
                        if getattr(node_obj, 'backorder_enabled', True):
                            self.customer_backorders[store_name][item_name] += (demand_qty - shipped)

            # 3. Planning (Store -> Warehouse -> Factory)
            logging.debug(f"--- Day {day}: Planning & Ordering ---")

            for node_name in self.node_order:
                current_node = self.nodes_map[node_name]

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
                        link_obj = self.network_map.get((parent_name, node_name))
                        replenishment_lt = link_obj.lead_time if link_obj else 0

                        profile = self.warehouse_demand_profiles.get(node_name, {}).get(item_name) if isinstance(current_node, WarehouseNode) else next((d for d in self.input.customer_demand if d.store_name == node_name and d.product_name == item_name), None)
                        if not profile: continue
                        demand_mean = profile['mean'] if isinstance(profile, dict) else profile.demand_mean
                        demand_std = profile['std_dev'] if isinstance(profile, dict) else profile.demand_std_dev

                        inv_on_hand = self.stock[node_name].get(item_name, 0)
                        # Include future pipeline shipments scheduled via pending_shipments and legacy in_transit_orders
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
                        for d, orders in self.in_transit_orders.items():
                            if d > day:
                                for it, q, dest, _src in orders:
                                    if dest == node_name and it == item_name:
                                        pipeline_incoming += q
                        # Future outbound commitments from this node (e.g., warehouse -> store)
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
                        # Subtract store customer backorders or warehouse scheduled outbound commitments
                        if isinstance(current_node, StoreNode):
                            inv_pos -= self.customer_backorders[node_name].get(item_name, 0.0)
                        elif isinstance(current_node, WarehouseNode):
                            inv_pos -= scheduled_outgoing
                        order_up_to = norm_ppf(current_node.service_level) * demand_std * math.sqrt(replenishment_lt) + demand_mean * (replenishment_lt + 1)
                        qty_to_order = max(0, math.ceil(order_up_to - inv_pos))
                        logging.debug(f"Day {day}: Node {node_name}, Item {item_name}: inv_pos={inv_pos}, order_up_to={order_up_to}, calculated qty_to_order={qty_to_order}")

                        if qty_to_order > 0:
                            # Apply link-level and node-level MOQ and order multiple if provided
                            node_moq = getattr(current_node, 'moq', {}).get(item_name, 0)
                            node_mult = getattr(current_node, 'order_multiple', {}).get(item_name, 0)
                            link_moq = getattr(link_obj, 'moq', {}).get(item_name, 0) if link_obj else 0
                            link_mult = getattr(link_obj, 'order_multiple', {}).get(item_name, 0) if link_obj else 0

                            # MOQ: enforce the larger (both constraints must be met)
                            effective_moq = max(node_moq or 0, link_moq or 0)
                            if 0 < qty_to_order < effective_moq:
                                qty_to_order = effective_moq

                            # Order multiple: enforce both. If both are positive integers, use LCM; else round sequentially.
                            def _is_int(x: float) -> bool:
                                return math.isclose(x, round(x))

                            eff_mult = 0
                            if (node_mult or 0) > 0 and (link_mult or 0) > 0:
                                if _is_int(node_mult) and _is_int(link_mult):
                                    a, b = int(round(node_mult)), int(round(link_mult))
                                    eff_mult = abs(a * b) // math.gcd(a, b)
                                else:
                                    # Fallback: apply both sequentially
                                    eff_mult = 0  # mark to use sequential rounding
                            if eff_mult:
                                qty_to_order = int(math.ceil(qty_to_order / eff_mult) * eff_mult)
                            else:
                                # Apply each multiple if present
                                for m in [node_mult, link_mult]:
                                    if m and m > 0:
                                        qty_to_order = int(math.ceil(qty_to_order / m) * m)

                            logging.debug(f"Day {day}: Replenishment order of {qty_to_order} for {item_name} from {node_name} to {parent_name}. Placing order via _place_order.")
                            self._place_order(parent_name, node_name, item_name, qty_to_order, day)
                
                # Factories use Service Level for finished goods, Min-Max for components
                if isinstance(current_node, FactoryNode):
                    # Plan finished goods production
                    logging.debug(f"Day {day}: Production planning for {node_name}")
                    for item_name in current_node.producible_products:
                        profile = self.factory_demand_profiles.get(node_name, {}).get(item_name)
                        if not profile: continue
                        # Include future scheduled completions (pipeline production)
                        pipeline_finished = 0.0
                        for d, orders in self.production_orders.items():
                            if d > day:
                                for i, q, f in orders:
                                    if f == node_name and i == item_name:
                                        pipeline_finished += q
                        inv_pos = self.stock[node_name].get(item_name, 0) + pipeline_finished
                        order_up_to = norm_ppf(current_node.service_level) * profile['std_dev'] * math.sqrt(current_node.lead_time) + profile['mean'] * (current_node.lead_time + 1)
                        production_needed = max(0, math.ceil(order_up_to - inv_pos))
                        # Target production quantity before material check
                        target_prod = (
                            production_needed if getattr(current_node, 'allow_production_over_capacity', True)
                            else min(production_needed, current_node.production_capacity)
                        )
                        # Cap by available components
                        if target_prod > 0:
                            max_by_components = float('inf')
                            for bom in self.products[item_name].assembly_bom:
                                avail = self.stock[node_name].get(bom.item_name, 0)
                                if bom.quantity_per > 0:
                                    max_by_components = min(max_by_components, math.floor(avail / bom.quantity_per))
                            producible_qty = max(0, min(int(target_prod), int(max_by_components if max_by_components != float('inf') else target_prod)))
                        else:
                            producible_qty = 0

                        if producible_qty > 0:
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
                        # Include pipeline component shipments (pending_shipments + legacy in_transit_orders)
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
                        for d, orders in self.in_transit_orders.items():
                            if d > day:
                                for it, q, dest, _src in orders:
                                    if dest == node_name and it == item_name:
                                        pipeline_incoming += q
                        inv_pos = inv_on_hand + pipeline_incoming
                        if inv_pos <= reorder_point:
                            order_up_to = current_node.order_up_to_level.get(item_name, inv_pos)
                            qty_to_order = max(0, order_up_to - inv_pos)
                            moq = current_node.moq.get(item_name, 0)
                            if 0 < qty_to_order < moq:
                                qty_to_order = moq
                            mult = current_node.order_multiple.get(item_name, 0)
                            if mult and mult > 0:
                                qty_to_order = int(math.ceil(qty_to_order / mult) * mult)
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
        logging.debug(f"DEBUG: Day {current_day}: Placing order for {item_name} qty {quantity} from {supplier_node_name} to {customer_node_name}.")
        # Record the order
        self.order_history[current_day].append((item_name, quantity, supplier_node_name, customer_node_name))
        self.cumulative_ordered[(customer_node_name, item_name)] += quantity
        # Schedule shipment after the link lead time (order-to-arrival)
        link_obj = self.network_map.get((supplier_node_name, customer_node_name))
        link_lt = link_obj.lead_time if link_obj else 0
        ship_day = current_day + link_lt
        # Initial schedule is not a backorder
        self.pending_shipments[ship_day].append((item_name, quantity, supplier_node_name, customer_node_name, False))
        

    def record_daily_snapshot(self, day, start_stock, end_stock, events):
        snapshot = {"day": day + 1, "nodes": {}}
        all_node_names = set(start_stock.keys()) | set(end_stock.keys())

        # Calculate ordered quantities from order_history for the current day (by destination)
        daily_ordered_quantities = defaultdict(lambda: defaultdict(float))
        for item, qty, _supplier, dest in self.order_history.get(day, []):
            if dest in self.nodes_map:
                daily_ordered_quantities[dest][item] += qty

        # Collect items that appeared only in events (not necessarily in start/end stock)
        event_items_by_node = defaultdict(set)
        for key in events.keys():
            # Skip special aggregated event keys (contain ':')
            if ':' in key:
                continue
            try:
                node_name, item_name = key.split('_', 1)
            except ValueError:
                continue
            event_items_by_node[node_name].add(item_name)

        # Compute backorder balances per node/item
        # (1) Sum of future supplier backorder shipments (pending_shipments with is_backorder)
        backorder_balance_map = defaultdict(lambda: defaultdict(float))
        future_days = [d for d in self.pending_shipments.keys() if d >= day + 1]
        for d in future_days:
            for rec in self.pending_shipments.get(d, []):
                if len(rec) == 5:
                    item, qty, supplier, _dest, is_backorder = rec
                    if is_backorder:
                        backorder_balance_map[supplier][item] += qty
                else:
                    # Legacy tuple without flag -> not counted as backorder
                    pass
        # (2) Customer backorders outstanding at stores
        for store_name, items in self.customer_backorders.items():
            for item, qty in items.items():
                if qty > 0:
                    backorder_balance_map[store_name][item] += qty

        # Iterate through nodes and items (including event-only items)
        for name in sorted(list(all_node_names | set(event_items_by_node.keys()))):
            node_snapshot = {}
            all_items = (
                set(start_stock.get(name, {}).keys())
                | set(end_stock.get(name, {}).keys())
                | set(event_items_by_node.get(name, set()))
            )

            for item in sorted(list(all_items)):
                event_key = f'{name}_{item}'
                item_snapshot = events.get(event_key, defaultdict(float))

                # Start/End stock
                item_snapshot["start_stock"] = start_stock.get(name, {}).get(item, 0)
                item_snapshot["end_stock"] = end_stock.get(name, {}).get(item, 0)

                # Add ordered_quantity from accumulated daily_ordered_quantities (by destination)
                item_snapshot["ordered_quantity"] = daily_ordered_quantities[name][item]

                # Ensure all metrics are present, defaulting to 0
                for metric in ['incoming', 'demand', 'sales', 'consumption', 'produced', 'shortage', 'backorder_balance']:
                    if metric not in item_snapshot:
                        item_snapshot[metric] = 0

                # Ensure identity: demand = sales + shortage
                # This makes tables consistent for all nodes
                item_snapshot["demand"] = item_snapshot.get("sales", 0) + item_snapshot.get("shortage", 0)

                # Update backorder balance (end-of-day)
                item_snapshot["backorder_balance"] = backorder_balance_map[name][item]

                node_snapshot[item] = item_snapshot

            if node_snapshot:  # Only add node if it has item data
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
        produced_by_factory = defaultdict(float)

        # Track transportation costs by link type from transport events captured on ship day
        transport_costs_by_type = defaultdict(lambda: defaultdict(float))
        links_with_fixed_cost_applied = set()

        for key, data in events.items():
            # Production variable costs at factories
            if '_' in key:
                node_name, item_name = key.split('_', 1)
                node = self.nodes_map.get(node_name)
                if node and 'produced' in data and isinstance(node, FactoryNode):
                    qty_prod = data['produced']
                    pl["flow_costs"]["production_variable"] += node.production_cost_variable * qty_prod
                    produced_by_factory[node_name] += qty_prod
                    nodes_produced.add(node_name)

            # Transport costs: keys like 'transport:supplier->dest:item'
            if key.startswith('transport:'):
                try:
                    rest = key.split(':', 1)[1]
                    route, shipped_item = rest.split(':', 1)
                    supplier_name, dest_name = route.split('->', 1)
                except Exception:
                    continue
                qty = data.get('qty', 0) or 0
                supplier = self.nodes_map.get(supplier_name)
                dest = self.nodes_map.get(dest_name)
                link = self.network_map.get((supplier_name, dest_name))
                if not supplier or not dest or not link or qty <= 0:
                    continue

                # Material cost applies when material supplier sends to factory (per item)
                if isinstance(supplier, MaterialNode) and isinstance(dest, FactoryNode):
                    pl["material_cost"] += supplier.material_cost.get(shipped_item, 0) * qty

                # Apply fixed transportation cost once per link per day
                link_key = (supplier_name, dest_name)
                if link_key not in links_with_fixed_cost_applied:
                    if isinstance(supplier, MaterialNode) and isinstance(dest, FactoryNode):
                        transport_costs_by_type["material_transport"]["fixed"] += link.transportation_cost_fixed
                    elif isinstance(supplier, FactoryNode) and isinstance(dest, WarehouseNode):
                        transport_costs_by_type["warehouse_transport"]["fixed"] += link.transportation_cost_fixed
                    elif isinstance(supplier, WarehouseNode) and isinstance(dest, StoreNode):
                        transport_costs_by_type["store_transport"]["fixed"] += link.transportation_cost_fixed
                    links_with_fixed_cost_applied.add(link_key)

                # Variable transportation cost by shipped qty
                if isinstance(supplier, MaterialNode) and isinstance(dest, FactoryNode):
                    transport_costs_by_type["material_transport"]["variable"] += link.transportation_cost_variable * qty
                elif isinstance(supplier, FactoryNode) and isinstance(dest, WarehouseNode):
                    transport_costs_by_type["warehouse_transport"]["variable"] += link.transportation_cost_variable * qty
                elif isinstance(supplier, WarehouseNode) and isinstance(dest, StoreNode):
                    transport_costs_by_type["store_transport"]["variable"] += link.transportation_cost_variable * qty
        
        # Add fixed production costs
        for node_name in nodes_produced:
            pl["flow_costs"]["production_fixed"] += self.nodes_map[node_name].production_cost_fixed

        # Production over-capacity costs (assessed on completion day)
        for node_name, qty_prod in produced_by_factory.items():
            node = self.nodes_map.get(node_name)
            if not isinstance(node, FactoryNode):
                continue
            prod_cap = getattr(node, 'production_capacity', float('inf'))
            allow_over = getattr(node, 'allow_production_over_capacity', True)
            if prod_cap == float('inf') or not allow_over:
                continue
            over_qty = max(0.0, qty_prod - prod_cap)
            if over_qty > 0:
                pl["flow_costs"]["production_variable"] += node.production_over_capacity_variable_cost * over_qty
                if node.production_over_capacity_fixed_cost > 0:
                    pl["flow_costs"]["production_fixed"] += node.production_over_capacity_fixed_cost

        # Consolidate transportation costs
        for transport_type, costs in transport_costs_by_type.items():
            pl["flow_costs"][f"{transport_type}_fixed"] = costs["fixed"]
            pl["flow_costs"][f"{transport_type}_variable"] = costs["variable"]

        # Transport over-capacity costs (from events produced on ship day)
        overage_fixed_applied = set()
        for key, data in events.items():
            if key.startswith('transport_overage:'):
                try:
                    route = key.split(':', 1)[1]
                    supplier_name, dest_name = route.split('->', 1)
                except Exception:
                    continue
                link = self.network_map.get((supplier_name, dest_name))
                if not link:
                    continue
                over_qty = data.get('qty', 0) or 0
                if over_qty <= 0:
                    continue
                supplier = self.nodes_map.get(supplier_name)
                dest = self.nodes_map.get(dest_name)
                if isinstance(supplier, MaterialNode) and isinstance(dest, FactoryNode):
                    ttype = "material_transport"
                elif isinstance(supplier, FactoryNode) and isinstance(dest, WarehouseNode):
                    ttype = "warehouse_transport"
                elif isinstance(supplier, WarehouseNode) and isinstance(dest, StoreNode):
                    ttype = "store_transport"
                else:
                    ttype = None
                if ttype:
                    pl["flow_costs"][f"{ttype}_variable"] += link.over_capacity_variable_cost * over_qty
                    lkey = (supplier_name, dest_name)
                    if lkey not in overage_fixed_applied and link.over_capacity_fixed_cost > 0:
                        pl["flow_costs"][f"{ttype}_fixed"] += link.over_capacity_fixed_cost
                        overage_fixed_applied.add(lkey)

        # Stock Costs
        # Collect storage overage quantities recorded during receipts/production
        storage_overage_qty_by_node = defaultdict(float)
        for key, data in events.items():
            if key.startswith('storage_overage:'):
                node_name = key.split(':', 1)[1]
                storage_overage_qty_by_node[node_name] += data.get('qty', 0) or 0

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
                # Add storage over-capacity costs (if any)
                over_qty = storage_overage_qty_by_node.get(node.name, 0)
                if over_qty > 0:
                    pl["stock_costs"][f"{cat}_variable"] += node.storage_over_capacity_variable_cost * over_qty
                    pl["stock_costs"][f"{cat}_fixed"] += node.storage_over_capacity_fixed_cost

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

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

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
