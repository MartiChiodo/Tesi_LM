from __future__ import annotations

import logging
from collections import defaultdict
from itertools import product

from Simulator.scripts.core.warehouse import Warehouse
from Simulator.scripts.opt.exact_optimization import *


# Constants

OBATCH_SIZE = 30
TIME_UNIT   = 20    # seconds per discrete period (Barnhart)
N_TIME      = 60    # number of discrete periods  → horizon = 20 × 60 = 1 200 s



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

        travelling_arcs = [
            [(l1, t1), (l2, t2)]
            for (l1, t1) in nodes
            for l2 in all_locations
            for t2 in range(t1 + 1, N_TIME)
            if l1 != l2
            and (t2 - t1) * TIME_UNIT >= warehouse.travel_time(
                warehouse.cell2coord(l1),
                warehouse.cell2coord(l2),
                random_generator=None,       # deterministic (no stochastic component)
            )
        ]

        idle_arcs = [
            [(l, t), (l, t + 1)]
            for (l, t) in product(all_locations, range(N_TIME))
            if t + 1 < N_TIME
        ]

        return nodes, travelling_arcs, idle_arcs


    # Simulation-dependent data extraction

    def _extract_orders(self, state, sim) -> tuple[list, list]:
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
                if remaining:
                    ws_orders.append(o)
                    ws_orders_items.append(remaining)

        orders       = backlog      + ws_orders
        orders_items = backlog_items + ws_orders_items
        return orders, orders_items
    

    def solve(self, state, sim):
        solve_exact_model(self, state, sim)



    