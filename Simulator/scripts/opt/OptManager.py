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
OBATCH_SIZE = 70    # max orders pulled from backlog per optimization cycle
TIME_UNIT   = 30    # seconds per discrete time period
N_TIME      = 70    # number of discrete periods in the scheduling horizon



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
                    1.1*warehouse.travel_time(
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
        orders, o_items, z1_sol, x1_sol, x2_sol, v2_sol, y2_sol, from_RelPod_to_PodId = \
            solve_by_decomposition(OptManager=self, sim=sim, state=state)

        # z1[m,w]   = 1  order m assigned to workstation w
        # x1[im,p] = 1  item i of order m retrieved from pod p
        # x2[im,t] = 1  item i of order m picked by time t (cumulative)
        # v2[m,t]   = 1  order m actively being served at time t

        n_orders = len(orders)
        relevant_pairs_for_x = [(i, m) for m in range(n_orders) 
                                for i in o_items[m]]

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


        ### Step 2: build lookup maps from solution

        order_to_ws: dict[int, int] = {
            m: w
            for m in range(n_orders)
            for w in range(self.n_workstations)
            if z1_sol[m, w] > 0.5
        }

        # (sku, order_idx) → actual pod_id
        item_to_pod: dict[tuple[int, int], int] = {}
        for im, (i, m) in enumerate(relevant_pairs_for_x):
            assigned = next(
                (p for p in range(self.n_pods) if x1_sol[im, p] > 0.5), None
            )
            if assigned is not None:
                item_to_pod[(i, m)] = assigned

        # (sku, order_idx) → timestep at which item is first picked
        item_to_time: dict[tuple[int, int], int] = {}
        for im, (i, m) in enumerate(relevant_pairs_for_x):
            if x2_sol[im, 0] > 0.5:
                item_to_time[(i, m)] = 0
            else:
                item_to_time[(i, m)] = next(
                    (t for t in range(1, self.N_TIME)
                     if x2_sol[im, t] > 0.5 and x2_sol[im, t - 1] < 0.5),
                    None
                )

        ### Step 3 & 4: reconstruct pod trajectories from y2_sol → Tasks

        workstation_positions = set(self._W)
        storage_positions = set(self._L)
        pos_to_ws = {
            state.warehouse.workstations[w].position: w
            for w in range(self.n_workstations)
        }

        # Precompute: for each (pod_id, t_arrival, w_idx) → items and orders to pick
        pick_at: dict[tuple[int, int, int], dict] = defaultdict(
            lambda: {"items": set(), "orders": set()}
        )
        for (i, m), p_id in item_to_pod.items():
            t = item_to_time.get((i, m))
            if t is None:
                continue
            w = order_to_ws.get(m)
            if w is None:
                continue
            pick_at[(p_id, t, w)]["items"].add(i)
            pick_at[(p_id, t, w)]["orders"].add(orders[m].order_id)


        tasks: list[Task] = []

        for rel_p, p_id in enumerate(from_RelPod_to_PodId):

            # Collect all arcs traversed by this pod, sorted by departure time
            traversed = sorted(
                (src[1], src[0], dst[1], dst[0])          # (t_src, loc_src, t_dst, loc_dst)
                for a_idx, (src, dst) in enumerate(self.all_arcs)
                if y2_sol[rel_p, a_idx] > 0.5
            )

            # Walk the trajectory and split into trips.
            # A trip = sequence of workstation visits between two storage stays.
            # A new trip starts when the pod departs from storage after returning.
            current_stops: list[tuple[int, int]] = []   # (t_arrival, w_idx)
            in_trip = False

            for t_src, _, t_dst, loc_dst in traversed:

                if loc_dst in workstation_positions and t_dst - t_src <= 1:
                    # Pod arrives at a workstation
                    w_idx = pos_to_ws[loc_dst]
                    current_stops.append((t_dst, w_idx))
                    in_trip = True

                elif loc_dst in workstation_positions and t_dst - t_src > 1:
                    # Pod arrives at a workstation but there was idle time → close current trip as a Task
                    stops = []
                    for t_arr, w_idx in current_stops:
                        data = pick_at.get((p_id, t_arr, w_idx))
                        if data and data["items"]:
                            stops.append(Visit(
                                workstation_id=w_idx,
                                orders=data["orders"],
                                items=data["items"],
                            ))
                    if stops:
                        pr = None
                        for i,m in [(i,m) for i,m in relevant_pairs_for_x if i in stops[0].items and orders[m].order_id in stops[0].orders]:
                            pr = item_to_time.get((i, m))
                            if not pr == None:
                                break 
                        tasks.append(Task(
                            task_id=None,
                            pod_id=p_id,
                            robot_id=None,
                            stops=stops,
                            priority=pr,
                        ))

                    # Begin new trip
                    w_idx = pos_to_ws[loc_dst]
                    current_stops = [(t_dst, w_idx)]
                    in_trip = True

                elif loc_dst in storage_positions and in_trip:
                    # Pod returns to storage → close current trip as a Task
                    stops = []
                    for t_arr, w_idx in current_stops:
                        data = pick_at.get((p_id, t_arr, w_idx))
                        if data and data["items"]:
                            stops.append(Visit(
                                workstation_id=w_idx,
                                orders=data["orders"],
                                items=data["items"],
                            ))
                    if stops:
                        pr = None
                        for i,m in [(i,m) for i,m in relevant_pairs_for_x if i in stops[0].items and orders[m].order_id in stops[0].orders]:
                            pr = item_to_time.get((i, m))
                            if not pr == None:
                                break 
                        tasks.append(Task(
                            task_id=None,
                            pod_id=p_id,
                            robot_id=None,
                            stops=stops,
                            priority=pr,
                        ))
                    current_stops = []
                    in_trip = False

            # Handle trip still open at end of horizon (pod never returned to storage)
            if current_stops:
                stops = []
                for t_arr, w_idx in current_stops:
                    data = pick_at.get((p_id, t_arr, w_idx))
                    if data and data["items"]:
                        stops.append(Visit(
                            workstation_id=w_idx,
                            orders=data["orders"],
                            items=data["items"],
                        ))
                if stops:
                    pr = None
                    for i,m in [(i,m) for i,m in relevant_pairs_for_x if i in stops[0].items and orders[m].order_id in stops[0].orders]:
                        pr = item_to_time.get((i, m))
                        if not pr == None:
                            break 
                    tasks.append(Task(
                        task_id=None,
                        pod_id=p_id,
                        robot_id=None,
                        stops=stops,
                        priority=pr,
                    ))

        # Assigning priority to task
        for task in tasks:
            t_picking =  task.priority
            ws = state.warehouse.workstations[task.stops[0].workstation_id]
            pod = state.warehouse.pods[task.pod_id]
            pr = (t_picking * self.TIME_UNIT - 0.5*state.warehouse.travel_time(
                    state.warehouse.cell2coord(ws.position),
                    state.warehouse.cell2coord(pod.storage_location)
                ))/self.N_TIME
            task.priority = pr

        # Sorting tasks according to priority
        tasks.sort(key=lambda t: t.priority)
        for new_id, task in enumerate(tasks):
            task.task_id = state.task_counter + new_id

        return orders, ordered_orders_by_w, tasks
