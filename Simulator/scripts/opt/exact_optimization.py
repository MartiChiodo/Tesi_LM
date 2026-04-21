import gurobipy as gb
from itertools import product

OBATCH_SIZE = 30

TIME_UNIT = 20   # in seconds (dalla Barnhart)
N_TIME = 60      # discrete periods (I optimize for the next 20*60 sec = 20 min)

def solve_exact_opt_model(sim):

    # Utlity 
    n_skus = sim.warehouse_status.num_skus
    n_pods = len(sim.warehouse_statuts.pods)
    set_of_pods = sim.warehouse_statuts.pods.deepcopy()
    pod_indices_by_sku = { i : sim.warehouse_statuts.get_pods_containing_sku(sku_id = i).pod_id for i in range(n_skus)}
    n_workstation = len(sim.warehouse_status.workstations)
    set_of_workstations = sim.warehouse_status.workstations.deepcopy()

    # TIME-SPACE NETWORKS ARCS
    L = [p.storage_location for p in set_of_pods]
    W = [w.position for w in set_of_workstations]
    nodes = list(product(L+W, range(N_TIME)))

    travelling_arcs = [
            [(l1, t1), (l2, t2)]
            for (l1, t1) in nodes
            for l2 in (L + W)
            for t2 in range(t1 + 1, N_TIME)
            if l1 != l2
            and (t2 - t1) * TIME_UNIT >= sim.warehouse_status.travel_time(
                sim.warehouse_status.cell2coord(l1),
                sim.warehouse_status.cell2coord(l2),
                None
            )
        ]
    
    idle_arcs = [
        [(l1, t1), (l1, t1 + 1)]
        for (l1, t1) in product(L+W, range(N_TIME))
        if t1 + 1 < N_TIME
    ]

    incoming_arc_per_node = {}
    outgoing_arc_per_node = {}
    for src, dst in travelling_arcs + idle_arcs:
        incoming_arc_per_node[dst].append(src)
        outgoing_arc_per_node[src].append(dst)




    ### SIM DEPENDING ######################################################

    # Get batch of order
    set_of_backlog_orders = sim.orders_in_system.pop_many(n = min(30, len(sim.orders_in_system)))
    set_of_order_items = [list(o.items_required) for o in set_of_backlog_orders]

    # To the batch of order I should add the currently opened orders and already enqueued ones
    set_of_orders_at_ws = []
    set_of_orders_at_ws_items = []
    for ws in set_of_workstations:

        tasks_list = [
            visit
            for id_t in ws.active_tasks
            for visit in sim.active_tasks[id_t].stops
            if visit.workstation_id == ws.workstation_id
        ]

        for id_o in ws.order_buffer:
            o = sim.orders_in_system.get(id_o)
            set_of_orders_at_ws.append(o)
            set_of_orders_at_ws_items.append(list[o.items_required])

        for id_o in ws.opened_orders:
            o = sim.orders_in_system.get(id_o)
            # I should accont for active tasks
            for v in tasks_list:
                if id_o in v.orders:
                    if len(o.items_pending - v.items) > 0:
                        set_of_orders_at_ws.append(o)
                        set_of_orders_at_ws_items.append(list[o.items_pending - v.items])

    orders = set_of_backlog_orders + set_of_orders_at_ws
    orders_item = set_of_order_items + set_of_orders_at_ws_items
    n_orders = len(set_of_orders_at_ws + set_of_backlog_orders)
        

    # When I run the optimization I build a model considering the active tasks as already performed
    model = gb.Model("TaskDesign")
    x = model.addVars(n_skus, n_orders, n_pods, n_workstation, N_TIME,
                   vtype=gb.BINARY, name="x")
    z = model.addVars(n_orders, n_workstation,
                  vtype=gb.BINARY, name="z")
    y = model.addVars(n_pods, len(travelling_arcs + idle_arcs),
                  vtype=gb.BINARY, name="y")
    v = model.addVars(n_orders, n_workstation, N_TIME,
                  vtype=gb.BINARY, name="v")
    f = model.addVars(n_orders, n_workstation, N_TIME,
                  vtype=gb.BINARY, name="f")
    g = model.addVars(n_orders, n_workstation, N_TIME,
                  vtype=gb.BINARY, name="g")
    

    # Costraints
    CAP_WS = sim.warehouse_status.workstations[0].order_capacity
    DELTA_ITEM = sim.warehouse_status.workstations[0].item_process_time
    DELTA_POD = sim.warehouse_status.workstations[0].pod_process_time

    # Workstation Constraints
    model.addConstrs(
            (gb.quicksum(z[m, w] for w in range(n_workstation)) <= 1 for m in range(n_orders)),
            name="assign o-ws"
        )
    model.addConstrs(
            (gb.quicksum(v[m, w, t] for m in range(n_orders)) <= CAP_WS 
                for w in range(n_workstation) for t in range(N_TIME)),
            name="ws_capacity"
        )
    model.addConstrs(
           (
            gb.quicksum(
                DELTA_ITEM * (x[i, m, p, w, t] - x[i, m, p, w, t-1])
                for m in range(n_orders)
                for i in orders_item[m]
                for p in pod_indices_by_sku[i]
            )
            + gb.quicksum(
                DELTA_POD * y[p, a]
                for p in range(n_pods)
                for a in outgoing_arc_per_node[(w, t)]
            )
            <= TIME_UNIT for w in range(n_workstation) for t in range(1, N_TIME)
        ),
            name="workload_restriction"
        )
    

    # Pod Operations and Congestion
    model.addConstrs(
        (gb.quicksum(y[ip,a] for a in outgoing_arc_per_node[(p.storage_location, 0)]) == 1 for ip, p in enumerate(set_of_pods)),
        name = "storage_loc"
    )
    model.addConstrs(
            (
            gb.quicksum(y[ip, a] for a in incoming_arc_per_node[node]) 
            - gb.quicksum(y[ip, a] for a in outgoing_arc_per_node[node]) 
            == 0
            for ip, p in enumerate(set_of_pods)
            for node in nodes
            if node[1] != N_TIME - 1
            and not (node[1] == 0 and node[0] == p.storage_location)
        ),
        name = "flow_conservation"
    )
    
    # TODO: CONGESTION CONSTR

    # Consistency Constraints
    model.addConstrs(
            (
                x[i, m, p, w, t] - x[i, m, p, w, t-1]
                <= gb.quicksum(y[p, a] for a in travelling_arcs + outgoing_arc_per_node[(w,t)])
                for m in range(n_orders) 
                for i in orders_item[m]
                for p in pod_indices_by_sku[i]
                for w in range(n_workstation)
                for t in range(1, N_TIME)
            ),
            name = "link_assign_flow"
        )
    model.addConstrs(
            (
            gb.quicksum(x[i, m, p, w, t] - x[i, m, p, w, t-1] for p in pod_indices_by_sku[i]) <= z[m, w]
            for m in range(n_orders) 
            for i in orders_item[m]
            for w in range(n_workstation)
            for t in range(1, N_TIME)
        ),
        name = "order_all_delivered_at_wst"
    )

    ## TODO : implementare vincoli 11 - 14

    return 