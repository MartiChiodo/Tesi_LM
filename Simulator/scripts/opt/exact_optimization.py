import logging
import gurobipy as gb

def solve_exact_model(OptManager, state, sim) -> None:
    """
    Construct the Gurobi model for the current simulation snapshot.

    Reads current orders and active tasks from *state*, then builds
    variables and constraints.  Call :meth:`solve` afterwards.

    Parameters
    ----------
    state : SimulatorState   Current mutable simulation state.
    sim   : Simulator        Provides config and RNG (read-only here).
    """
    orders, orders_items = OptManager._extract_orders(state, sim)
    n_orders = len(orders)

    if n_orders == 0:
        logging.debug("[OptManager] No orders to optimise — skipping model build.")
        model = None
        return

    n_p  = OptManager.n_pods
    n_w  = OptManager.n_workstations
    n_a  = len(OptManager.all_arcs)

    model = gb.Model("TaskDesign")
    model.setParam("OutputFlag", 0)     # suppress Gurobi console output

    # Variables 
    x = model.addVars(OptManager.n_skus, n_orders, n_p, n_w, OptManager.N_TIME,
                        vtype=gb.GRB.BINARY, name="x")
    z = model.addVars(n_orders, n_w,
                        vtype=gb.GRB.BINARY, name="z")
    y = model.addVars(n_p, n_a,
                        vtype=gb.GRB.BINARY, name="y")
    v = model.addVars(n_orders, n_w, OptManager.N_TIME,
                        vtype=gb.GRB.BINARY, name="v")
    f = model.addVars(n_orders, n_w, OptManager.N_TIME,
                        vtype=gb.GRB.BINARY, name="f")
    g = model.addVars(n_orders, n_w, OptManager.N_TIME,
                        vtype=gb.GRB.BINARY, name="g")

    # Constraints

    # Each order assigned to at most one workstation
    model.addConstrs(
        (gb.quicksum(z[m, w] for w in range(n_w)) <= 1
            for m in range(n_orders)),
        name="assign_o_ws"
    )

    # Workstation order capacity
    model.addConstrs(
        (gb.quicksum(v[m, w, t] for m in range(n_orders)) <= OptManager.CAP_WS
            for w in range(n_w) for t in range(OptManager.N_TIME)),
        name="ws_capacity"
    )

    # Workload restriction per time period
    model.addConstrs(
        (
            gb.quicksum(
                OptManager.DELTA_ITEM * (x[i, m, p, w, t] - x[i, m, p, w, t - 1])
                for m in range(n_orders)
                for i in orders_items[m]
                for p in OptManager.pod_indices_by_sku[i]
            )
            + gb.quicksum(
                OptManager.DELTA_POD * y[p, a]
                for p in range(n_p)
                for a in OptManager.outgoing_arc_idx[(w, t)]
            )
            <= OptManager.TIME_UNIT
            for w in range(n_w) for t in range(1, OptManager.N_TIME)
        ),
        name="workload_restriction"
    )

    # Pods start at their storage locations
    model.addConstrs(
        (
            gb.quicksum(y[ip, a] for a in OptManager.outgoing_arc_idx[(pod.storage_location, 0)])
            == 1
            for ip, pod in enumerate(OptManager._warehouse.pods)
        ),
        name="storage_loc"
    )

    # Flow conservation
    model.addConstrs(
        (
            gb.quicksum(y[ip, a] for a in OptManager.incoming_arc_idx[node])
            - gb.quicksum(y[ip, a] for a in OptManager.outgoing_arc_idx[node])
            == 0
            for ip, pod in enumerate(OptManager._warehouse.pods)
            for node in OptManager.nodes
            if node[1] != OptManager.N_TIME - 1
            and not (node[1] == 0 and node[0] == pod.storage_location)
        ),
        name="flow_conservation"
    )

    # Link assignment to pod flow
    model.addConstrs(
        (
            x[i, m, p, w, t] - x[i, m, p, w, t - 1]
            <= gb.quicksum(y[p, a] for a in OptManager.outgoing_arc_idx[(w, t)])
            for m in range(n_orders)
            for i in orders_items[m]
            for p in OptManager.pod_indices_by_sku[i]
            for w in range(n_w)
            for t in range(1, OptManager.N_TIME)
        ),
        name="link_assign_flow"
    )

    # All items of an order delivered at the assigned workstation
    model.addConstrs(
        (
            gb.quicksum(
                x[i, m, p, w, t] - x[i, m, p, w, t - 1]
                for p in OptManager.pod_indices_by_sku[i]
            )
            <= z[m, w]
            for m in range(n_orders)
            for i in orders_items[m]
            for w in range(n_w)
            for t in range(1, OptManager.N_TIME)
        ),
        name="order_all_delivered_at_ws"
    )

    # TODO: constraints 11-14 (congestion)

    logging.info("[OptManager] Model built: %d orders, %d variables.",
                    n_orders, model.NumVars)
    
    ### OBJECTIVE FUNCTION
    model.setObjective(
        (gb.quicksum(x[i,m,p,w,OptManager.N_TIME-1])
         for m in range(n_orders)
         for i in orders_items[m]
         for p in OptManager.pod_indices_by_sku[i]
         for w in range(n_w)),
        sense=gb.GRB.MAZIMIXE
    )
    

    ### SOLVING
    model.optimize()
    status = model.Status

    if status == gb.GRB.OPTIMAL:
        logging.info("[OptManager] Optimal solution found.  Obj = %.4f",
                        model.ObjVal)
    elif status == gb.GRB.INFEASIBLE:
        logging.warning("[OptManager] Model is infeasible.")
    else:
        logging.warning("[OptManager] Solve ended with status %d.", status)
