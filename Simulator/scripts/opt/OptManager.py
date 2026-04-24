from __future__ import annotations

import logging
from collections import defaultdict
from itertools import product
import numpy as np

from Simulator.scripts.core.warehouse import Warehouse
from Simulator.scripts.core.entities import Visit, Task
from Simulator.scripts.core.enums import OrderStatus
from Simulator.scripts.opt.decomposition_benchmark import solve_by_decomposition


### CONSTANTS
OBATCH_SIZE = 50    # max orders pulled from backlog per optimization cycle
TIME_UNIT   = 30    # seconds per discrete time period
N_TIME      = 100    # number of discrete periods in the scheduling horizon



class OptManager:
    """
    Manages the MIP optimization pipeline for the warehouse simulator.

    Static data (topology, time-space network) is computed once at construction.
    Simulation-dependent data (orders, tasks) is injected at each optimization call.

    Attributes
    ----------
    nodes               : list[tuple]            All (location, time) nodes in the network.
    travelling_arcs     : list[list[tuple]]      Arcs representing feasible pod movements.
    idle_arcs           : list[list[tuple]]      Arcs representing pods staying in place.
    all_arcs            : list[list[tuple]]      travelling_arcs + idle_arcs.
    incoming_arc_idx    : dict[tuple, list[int]] Arc indices arriving at each node.
    outgoing_arc_idx    : dict[tuple, list[int]] Arc indices leaving each node.
    pod_indices_by_sku  : dict[int, list[int]]   Pod indices that stock each SKU.
    """

    def __init__(self, warehouse: Warehouse) -> None:
        self._warehouse = warehouse

        self.n_skus         = warehouse.num_skus
        self.n_pods         = len(warehouse.pods)
        self.n_workstations = len(warehouse.workstations)

        # Pod storage locations and workstation positions (used in arc construction)
        self._L = [p.storage_location for p in warehouse.pods]
        self._W = [ws.position        for ws in warehouse.workstations]

        # SKU → pods that carry it (used to restrict x1/x2 domains)
        self.pod_indices_by_sku: dict[int, list[int]] = defaultdict(list)
        for ip, pod in enumerate(warehouse.pods):
            for sku in pod.items:
                self.pod_indices_by_sku[sku].append(ip)

        # Workstation parameters (assumed uniform across all stations)
        ws0 = warehouse.workstations[0]
        self.CAP_WS     = ws0.order_capacity
        self.DELTA_ITEM = ws0.item_process_time
        self.DELTA_POD  = ws0.pod_process_time
        self.N_TIME     = N_TIME
        self.TIME_UNIT  = TIME_UNIT

        logging.info("[OptManager] Building time-space network ...")
        self.nodes, self.travelling_arcs, self.idle_arcs = \
            self.build_network(warehouse, self._L, self._W)

        self.all_arcs = self.travelling_arcs + self.idle_arcs

        # Index arcs by destination and source node for fast constraint generation
        self.incoming_arc_idx: dict[tuple, list[int]] = defaultdict(list)
        self.outgoing_arc_idx: dict[tuple, list[int]] = defaultdict(list)
        for idx, (src, dst) in enumerate(self.all_arcs):
            self.outgoing_arc_idx[src].append(idx)
            self.incoming_arc_idx[dst].append(idx)

        logging.info(
            "[OptManager] Network ready: %d nodes, %d travelling arcs, %d idle arcs.",
            len(self.nodes), len(self.travelling_arcs), len(self.idle_arcs),
        )


    ### NETWORK CONSTRUCTION 

    def build_network(
        self,
        warehouse: Warehouse,
        L: list[int],
        W: list[int],
    ) -> tuple[list, list, list]:
        """
        Build the time-space network for pod routing.

        Nodes are (location, time) pairs. Travelling arcs connect locations
        reachable within the horizon; idle arcs represent staying in place.
        Only pod↔workstation and workstation↔workstation movements are modelled
        (pod↔pod arcs are excluded by design).
        """
        all_locations = L + W
        nodes = list(product(all_locations, range(N_TIME)))

        # Discretize pairwise travel times (ceiling to nearest time unit)
        travel_dt: dict[tuple, int] = {}
        for l1 in all_locations:
            for l2 in all_locations:
                if l1 == l2:
                    continue
                travel_dt[(l1, l2)] = int(np.ceil(
                    warehouse.travel_time(
                        warehouse.cell2coord(l1),
                        warehouse.cell2coord(l2),
                        None,
                    ) / TIME_UNIT
                ))

        travelling_arcs = []

        def _add_arcs(sources, destinations):
            """Append time-feasible arcs from each source location to each destination."""
            for l1 in sources:
                for l2 in destinations:
                    if l1 == l2:
                        continue
                    dt = travel_dt[(l1, l2)]
                    if dt >= N_TIME:
                        continue
                    for t1 in range(N_TIME - dt):
                        travelling_arcs.append([(l1, t1), (l2, t1 + dt)])

        _add_arcs(L, W)   # pod   → workstation
        _add_arcs(W, L)   # workstation → pod
        _add_arcs(W, W)   # workstation → workstation

        # Idle arcs: pod/workstation stays at the same location each period
        idle_arcs = [
            [(loc, t), (loc, t + 1)]
            for (loc, t) in product(all_locations, range(N_TIME))
            if t + 1 < N_TIME
        ]

        return nodes, travelling_arcs, idle_arcs


    ### ORDER EXTRACTION 

    def extract_orders(self, state) -> tuple[list, list]:
        """
        Collect the orders to optimize and their pending item lists.

        Combines a fresh backlog batch with orders already at workstations.
        For open orders, items already covered by active tasks are subtracted.

        Returns
        -------
        orders       : list[Order]
        orders_items : list[list[int]]   Pending SKU list per order (same index).
        """
        ws_orders       = []
        ws_orders_items = []

        for ws in state.warehouse.workstations:
            # Visits currently being processed at this workstation
            active_visits = [
                visit
                for task_id in ws.active_tasks
                for visit in state.active_tasks[task_id].stops
                if visit.workstation_id == ws.workstation_id
            ]

            # Buffered orders: all items still pending
            for order_id in ws.order_buffer:
                o = state.orders_in_system.get(order_id)
                if o is not None:
                    ws_orders.append(o)
                    ws_orders_items.append(list(o.items_required))

            # Open orders: exclude items already claimed by active task visits
            for order_id in ws.opened_orders:
                o = state.orders_in_system.get(order_id)
                if o is None:
                    continue
                covered = {
                    item
                    for visit in active_visits
                    if order_id in visit.orders
                    for item in visit.items
                }
                remaining = list(o.items_pending - covered)
                if remaining:
                    ws_orders.append(o)
                    ws_orders_items.append(remaining)

        # Backlog orders
        backlog = []
        backlog_items = []

        n_to_consider = min(OBATCH_SIZE - len(ws_orders), len(state.orders_in_system))
        l_to_push = []

        while len(backlog) < n_to_consider and len(state.orders_in_system) > 0:
            o = state.orders_in_system.pop()
            l_to_push.append(o)
            if o.status == OrderStatus.BACKLOG:
                backlog.append(o)
                backlog_items.append(list(o.items_pending))

        for o in l_to_push:
            state.orders_in_system.push(o)

        return ws_orders + backlog, ws_orders_items + backlog_items



    ### TASK DESIGN AND ASSIGNMENT 

    def solve_task_design_and_assignment(self, sim, state):
        """
        Run the optimization problem and convert the solution into Task objects.

        Calls the optimizer, then:
        1. Maps each order to its assigned workstation and start time.
        2. Determines which pod visits which workstation at which time step.
        3. Groups consecutive active time steps per pod into Task objects.

        Returns
        -------
        orders               : list[Order]
        ordered_orders_by_w  : dict[int, list[int]]   Order indices sorted by start time, per workstation.
        tasks                : list[Task]
        """
        orders, z1_sol, x1_sol, x2_sol, v2_sol = solve_by_decomposition(
            OptManager=self, sim=sim, state=state
        )

        # z1[m,w]   = 1  order m assigned to workstation w
        # x1[im,p] = 1  item i of order m retrieved from pod p
        # x2[im,t] = 1  item i of order m picked by time t (cumulative)
        # v2[m,t]   = 1  order m actively being served at time t

        n_orders = len(orders)
        relevant_pairs_for_x = [(i, m) for m in range(n_orders) 
                                for i in state.orders_in_system.get(orders[m].order_id).items_pending]

        ### Step 1: extract workstation assignments and order start times 

        orders_by_workstation: dict[int, list[int]] = {w: [] for w in range(self.n_workstations)}
        order_start_time: dict[int, int] = {}

        for m in range(n_orders):
            for w in range(self.n_workstations):
                if z1_sol[m, w] > 0.5:
                    orders_by_workstation[w].append(m)
                    break

            # Already-open orders start immediately; others use first active v2 period
            if orders[m].order_id in state.warehouse.workstations[w].opened_orders:
                start_t = 0
            else:
                start_t = next(
                    (t for t in range(self.N_TIME) if v2_sol[m, t] > 0.5),
                    None,   # fallback: do not consider if never active
                )
            if start_t is None:
                orders_by_workstation[w].remove(m)
            else:
                order_start_time[m] = start_t

        # Sort orders within each workstation by start time for downstream processing
        ordered_orders_by_w = {
            w: sorted(idxs, key=lambda m: order_start_time[m])
            for w, idxs in orders_by_workstation.items()
        }


        ### Step 2: build lookup maps from solution s

        # order index → workstation index
        order_to_ws: dict[int, int] = {
            m: w
            for m in range(n_orders)
            for w in range(self.n_workstations)
            if z1_sol[m, w] > 0.5
        }

        # (sku, order_idx) → pod index
        item_to_pod: dict[tuple[int, int], int] = {}
        for im, (i,m) in enumerate(relevant_pairs_for_x):
            item_to_pod[(i,m)] = next(
                p for p in range(self.n_pods) if x1_sol[im, p] > 0.5
            )

        # (sku, order_idx) → time step at which the item is first picked
        item_to_time: dict[tuple[int, int], int] = {}
        for im, (i,m) in enumerate(relevant_pairs_for_x):
            if x2_sol[im, 0] > 0.5:
                item_to_time[(i, m)] = 0
            else:
                item_to_time[(i, m)] = next(
                    (t for t in range(1, self.N_TIME)
                    if x2_sol[im, t] > 0.5 and x2_sol[im, t - 1] < 0.5),
                    None
                )


        ### Step 3: aggregate pod activity by (time, workstation)

        # pod_activity[p][(t, w)] → {"items": set, "orders": set}
        pod_activity: dict[int, dict[tuple[int, int], dict]] = defaultdict(
            lambda: defaultdict(lambda: {"items": set(), "orders": set()})
        )
        for (i, m), p in item_to_pod.items():
            if (i, m) not in item_to_time:
                continue
            t = item_to_time[(i, m)]
            if not t is None:
                w = order_to_ws[m]
                pod_activity[p][(t, w)]["items"].add(i)
                pod_activity[p][(t, w)]["orders"].add(orders[m].order_id)


        ### Step 4: group consecutive active time steps into Tasks 

        # Contiguous periods (|t1-t2| ≤ 1) for the same pod form a single task.
        # Within each block, visits are split by destination workstation.
        tasks: list[Task] = []
        task_id = state.task_counter

        for p, tw_data in pod_activity.items():
            active_ts = sorted({t for (t, _) in tw_data})

            # Identify contiguous blocks
            blocks: list[list[int]] = []
            current_block = [active_ts[0]]
            for t in active_ts[1:]:
                if t - current_block[-1] <= 1:
                    current_block.append(t)
                else:
                    blocks.append(current_block)
                    current_block = [t]
            blocks.append(current_block)

            for block in blocks:
                # Merge items/orders for each workstation visited in this block
                ws_data: dict[int, dict] = defaultdict(lambda: {"items": set(), "orders": set()})
                for t in block:
                    for (bt, w), data in tw_data.items():
                        if bt == t:
                            ws_data[w]["items"].update(data["items"])
                            ws_data[w]["orders"].update(data["orders"])

                stops = [
                    Visit(workstation_id=w, orders=d["orders"], items=d["items"])
                    for w, d in ws_data.items()
                ]
                tasks.append(Task(
                    task_id=task_id,
                    pod_id=p,
                    robot_id=None,
                    stops=stops,
                    priority=min(block),   # earlier block → higher priority
                ))
                task_id += 1

        state.task_counter = task_id
        return orders, ordered_orders_by_w, tasks