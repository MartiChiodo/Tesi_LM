from __future__ import annotations

import logging
from collections import defaultdict
from itertools import product
import numpy as np

from Simulator.scripts.core.warehouse import Warehouse
from Simulator.scripts.core.entities import Visit, Task
from Simulator.scripts.opt.decomposition_benchmark import solve_by_decomposition


# Constants

OBATCH_SIZE = 50
TIME_UNIT   = 20    # seconds per discrete period 
N_TIME      = 60   # number of discrete periods  



# OptManager

class OptManager:
    """
    Static data (warehouse topology, time-space network) is computed once at
    construction time.  Simulation-dependent data (orders, active tasks) is
    injected each time :meth:`build_exact_model` is called.

    Attributes
    ----------
    nodes               : list[tuple]              All (location, time) nodes.
    travelling_arcs     : list[list[tuple]]        Arcs representing possible pod movements.
    idle_arcs           : list[list[tuple]]        Arcs representing pod staying put.
    all_arcs            : list[list[tuple]]        travelling_arcs + idle_arcs.
    incoming_arc_idx    : dict[tuple, list[int]]   Indices into all_arcs of arcs arriving at each node.
    outgoing_arc_idx    : dict[tuple, list[int]]   Indices into all_arcs of arcs leaving each node.
    pod_indices_by_sku  : dict[int, list[int]]     Pod indices that contain each SKU.
    """

    def __init__(self, warehouse: Warehouse) -> None:
        self._warehouse = warehouse

        ####  Warehouse scalars
        self.n_skus         = warehouse.num_skus
        self.n_pods         = len(warehouse.pods)
        self.n_workstations = len(warehouse.workstations)

        # Pod and workstation location identifiers
        L = [p.storage_location for p in warehouse.pods]
        W = [ws.position        for ws in warehouse.workstations]
        self._L = L
        self._W = W

        # SKU → list of pod indices that carry it
        self.pod_indices_by_sku: dict[int, list[int]] = defaultdict(list)
        for ip, pod in enumerate(warehouse.pods):
            for sku in pod.items:
                self.pod_indices_by_sku[sku].append(ip)

        # Workstation processing parameters (assumed uniform across stations)
        ws0 = warehouse.workstations[0]
        self.CAP_WS     = ws0.order_capacity
        self.DELTA_ITEM = ws0.item_process_time
        self.DELTA_POD  = ws0.pod_process_time
        self.N_TIME = N_TIME
        self.TIME_UNIT = TIME_UNIT

        ### Time-space network 
        logging.info("[OptManager] Building time-space network ...")
        self.nodes, self.travelling_arcs, self.idle_arcs = \
            self._build_network(warehouse, L, W)

        self.all_arcs = self.travelling_arcs + self.idle_arcs

        self.incoming_arc_idx: dict[tuple, list[int]] = defaultdict(list)
        self.outgoing_arc_idx: dict[tuple, list[int]] = defaultdict(list)
        for idx, (src, dst) in enumerate(self.all_arcs):
            self.outgoing_arc_idx[src].append(idx)
            self.incoming_arc_idx[dst].append(idx)

        logging.info(
            "[OptManager] Network ready: %d nodes, %d travelling arcs, %d idle arcs.",
            len(self.nodes), len(self.travelling_arcs), len(self.idle_arcs)
        )

    
    # Network construction (static)
    def _build_network(
        self,
        warehouse: Warehouse,
        L: list[int],
        W: list[int],
    ) -> tuple[list, list, list]:
        """
        Build nodes, travelling arcs and idle arcs for the time-space network.
        """

        all_locations = L + W
        nodes = list(product(all_locations, range(N_TIME)))

        # Precompute travel times (discretized)
        travel_dt = {}
        for l1 in all_locations:
            for l2 in all_locations:
                if l1 == l2:
                    continue

                travel_dt[(l1, l2)] = int(np.ceil(
                    warehouse.travel_time(
                        warehouse.cell2coord(l1),
                        warehouse.cell2coord(l2),
                        None
                    ) / TIME_UNIT
                ))

        # Travelling arcs (time-feasible only and only pod -> wst, wst -> pod e wst -> wst) 
        travelling_arcs = []

        # POD -> WST
        for l1 in L:
            for l2 in W:
                dt = travel_dt[(l1, l2)]
                if dt >= N_TIME:
                    continue

                for t1 in range(N_TIME - dt):
                    travelling_arcs.append(
                        [(l1, t1), (l2, t1 + dt)]
                    )

        # WST -> POD
        for l1 in W:
            for l2 in L:
                dt = travel_dt[(l1, l2)]
                if dt >= N_TIME:
                    continue

                for t1 in range(N_TIME - dt):
                    travelling_arcs.append(
                        [(l1, t1), (l2, t1 + dt)]
                    )

        # WST -> WST
        for l1 in W:
            for l2 in W:
                if l1 == l2:
                    continue

                dt = travel_dt[(l1, l2)]
                if dt >= N_TIME:
                    continue

                for t1 in range(N_TIME - dt):
                    travelling_arcs.append(
                        [(l1, t1), (l2, t1 + dt)]
                    )

        # Idle arcs (stay in same location)
        idle_arcs = [
            [(l, t), (l, t + 1)]
            for (l, t) in product(all_locations, range(N_TIME))
            if t + 1 < N_TIME
        ]

        return nodes, travelling_arcs, idle_arcs


    # Simulation-dependent data extraction

    def _extract_orders(self, state) -> tuple[list, list]:
        """
        Extract the batch of orders and their pending item lists from the
        current simulation state.

        Returns
        -------
        orders       : list[Order]       Orders to optimise over.
        orders_items : list[list[int]]   Corresponding pending SKU lists.
        """
        # Backlog batch
        backlog = state.orders_in_system.pop_many(
            n=min(OBATCH_SIZE, len(state.orders_in_system))
        )
        backlog_items = [list(o.items_required) for o in backlog]

        # Orders already at workstations (open or buffered)
        ws_orders      = []
        ws_orders_items = []

        for ws in state.warehouse.workstations:
            # Active visits at this workstation (to subtract already-covered items)
            active_visits = [
                visit
                for task_id in ws.active_tasks
                for visit in state.active_tasks[task_id].stops
                if visit.workstation_id == ws.workstation_id
            ]

            # Buffered orders — full items_required still pending
            for order_id in ws.order_buffer:
                o = state.orders_in_system.get(order_id)
                if o is not None:
                    ws_orders.append(o)
                    ws_orders_items.append(list(o.items_required))

            # Open orders — subtract items already covered by active tasks
            for order_id in ws.opened_orders:
                o = state.orders_in_system.get(order_id)
                if o is None:
                    continue
                covered = set()
                for visit in active_visits:
                    if order_id in visit.orders:
                        covered |= visit.items
                remaining = list(o.items_pending - covered)
                if len(remaining) > 0:
                    ws_orders.append(o)
                    ws_orders_items.append(remaining)

        orders       = backlog      + ws_orders
        orders_items = backlog_items + ws_orders_items
        return orders, orders_items
    


    def solve_task_design_and_assignment(self, sim, state):

        orders, z1_sol, x1_sol, x2_sol, v2_sol = solve_by_decomposition(OptManager=self, sim=sim, state=state)

        """
        z1[m,w] = 1 if order m is open at workstation w
        v2[m,t] = 1 if ordem m is open at time t
        x1[i,m,p] = 1 if item i for order m is picked from pod p
        x2[i,m,t] = 1 if item i for order m is picked by time t
        """

        # From binary variables to tasks and assignments
        n_orders = len(orders)
        
        orders_by_workstation = {w: [] for w in range(self.n_workstations)}
        order_start_time = {}
        for m in range(n_orders):
            # workstation assignment
            for w in range(self.n_workstations):
                if z1_sol[m, w] > 0.5:
                    orders_by_workstation[w].append(m)

            # start time extraction
            start_t = None
            if orders[m].order_id in state.warehouse.workstations[w].opened_orders:
                start_t = 0
            else:
                for t in range(self.N_TIME):
                    if v2_sol[m, t] > 0.5:
                        start_t = t
                        break

            # fallback if never set
            order_start_time[m] = start_t if start_t is not None else self.N_TIME

        ordered_orders_by_w = {}
        for w in range(self.n_workstations):
            ordered_orders_by_w[w] = sorted(
                orders_by_workstation[w],
                key=lambda m: order_start_time[m]
            )


        ### TASK DESIGN 

        # Lookup maps
        order_to_ws: dict[int, int] = {}
        for m in range(n_orders):
            for w in range(self.n_workstations):
                if z1_sol[m, w] > 0.5:
                    order_to_ws[m] = w
                    break

        item_to_pod: dict[tuple[int, int], int] = {}
        for m in range(n_orders):
            for i in orders[m].items_pending:
                for p in range(self.n_pods):
                    if x1_sol[i, m, p] > 0.5:
                        item_to_pod[(i, m)] = p
                        break

        item_to_time: dict[tuple[int, int], int] = {}
        for m in range(n_orders):
            for i in orders[m].items_pending:
                if x2_sol[i, m, 0] > 0.5:
                    item_to_time[(i, m)] = 0
                    continue
                for t in range(1, self.N_TIME):
                    if x2_sol[i, m, t] > 0.5 and x2_sol[i, m, t - 1] < 0.5:
                        item_to_time[(i, m)] = t
                        break


        # Per ogni pod: (t, w) → {items, orders} 
        # pod_activity[p][(t, w)] = {"items": set, "orders": set}
        pod_activity: dict[int, dict[tuple[int,int], dict]] = defaultdict(
            lambda: defaultdict(lambda: {"items": set(), "orders": set()})
        )

        for (i, m), p in item_to_pod.items():
            if (i, m) not in item_to_time:
                continue
            t = item_to_time[(i, m)]
            w = order_to_ws[m]
            pod_activity[p][(t, w)]["items"].add(i)
            pod_activity[p][(t, w)]["orders"].add(orders[m].order_id)


        # Raggruppa timestep consecutivi per pod → blocchi = task
        # Per ogni pod, ordina i timestep attivi e raggruppa quelli contigui (|t1-t2|<=1).
        # Ogni blocco contiguo diventa un task; dentro ogni blocco si splitta per workstation.

        tasks: list[Task] = []
        task_id = state.task_counter

        for p, tw_data in pod_activity.items():
            active_ts = sorted(set(t for (t, w) in tw_data.keys()))

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

                task = Task(
                    task_id=task_id,
                    pod_id=p,
                    robot_id=None,
                    stops=stops,
                    priority=min(block),  
                )
                task_id += 1
                tasks.append(task)


                                
        state.task_counter = task_id
        return orders, ordered_orders_by_w, tasks    






    