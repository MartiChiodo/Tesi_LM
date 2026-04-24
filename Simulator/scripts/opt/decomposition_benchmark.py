import logging
import gurobipy as gb


def solve_by_decomposition(OptManager, sim, state):
    """
    Solve the warehouse optimization via two-stage MIP decomposition.

    Stage 1 — Assignment: assign orders to workstations (z) and items to pods (x/y).
    Stage 2 — Scheduling: route pods over time (y2) and schedule item picks (x2/v2).
    """

    orders, orders_items = OptManager.extract_orders(state)
    n_orders = len(orders)

    if n_orders == 0:
        logging.debug("[OptManager] No orders to optimise — skipping model build.")
        return

    n_p = OptManager.n_pods
    n_w = OptManager.n_workstations
    n_a = len(OptManager.all_arcs)


    ### STAGE 1: ORDER-WORKSTATION AND ORDER-ITEM-POD ASSIGNMENT

    logging.info("Building first stage problem ...")
    model1 = gb.Model('OW_OIP_Assignments')

    # z1[m,w]   = 1 if order m is assigned to workstation w
    # x1[i,m,p] = 1 if item i of order m is retrieved from pod p
    # y1[w,p]   = 1 if pod p must visit workstation w (derived from x1 and z1)
    z1 = model1.addVars(n_orders, n_w,                        vtype=gb.GRB.BINARY)
    x1 = model1.addVars(OptManager.n_skus, n_orders, n_p,    vtype=gb.GRB.BINARY)
    y1 = model1.addVars(n_w, n_p,                            vtype=gb.GRB.BINARY)

    # EC7: each order is assigned to exactly one workstation
    for m in range(n_orders):
        model1.addLConstr(
            gb.quicksum(z1[m, w] for w in range(n_w)),
            gb.GRB.EQUAL, 1, name='EC7')

    for m in range(n_orders):
        # EC8: each item of the order is retrieved from exactly one pod that stocks it
        for i in orders_items[m]:
            model1.addLConstr(
                gb.quicksum(x1[i, m, p] for p in OptManager.pod_indices_by_sku[i]),
                gb.GRB.EQUAL, 1, name='EC8')

        # EC10: y1[w,p] is forced to 1 when both x1[i,m,p] and z1[m,w] are 1
        for w in range(n_w):
            for i in orders_items[m]:
                for p in OptManager.pod_indices_by_sku[i]:
                    model1.addLConstr(
                        y1[w, p], gb.GRB.GREATER_EQUAL,
                        x1[i, m, p] + z1[m, w] - 1, name='EC10')

    # EC11: workload balancing — each workstation handles between 10% and 90% of total items
    total_items = sum(len(i) for i in orders_items)
    lower_I = total_items * 1 / 10
    upper_I = total_items * 9 / 10
    for w in range(n_w):
        items_at_w = gb.quicksum(z1[m, w] * len(orders_items[m]) for m in range(n_orders))
        model1.addLConstr(items_at_w, gb.GRB.LESS_EQUAL,    upper_I, name='EC11_upper')
        model1.addLConstr(items_at_w, gb.GRB.GREATER_EQUAL, lower_I, name='EC11_lower')

    # Fix assignment for orders already open at each workstation
    for w in range(n_w):
        for id_o in state.warehouse.workstations[w].opened_orders:
            m = next((i for i, o in enumerate(orders) if o.order_id == id_o), None)
            model1.addLConstr(z1[m, w] == 1, name='InitialCond')

    # Minimize total pod-workstation visits (proxy for travel distance)
    model1.setObjective(
        gb.quicksum(y1[w, p] for w in range(n_w) for p in range(n_p)),
        sense=gb.GRB.MINIMIZE)

    logging.info("Model1 built. Solving ...")
    model1.optimize()
    logging.info("Model1 solved. Status %s   [2: OPTIMAL, 3: INFEASIBLE, 9: TIME LIMIT]",
                 model1.Status)

    if model1.Status == gb.GRB.INFEASIBLE:
        model1.computeIIS()
        model1.write("scripts/opt/iis.ilp")

    # Extract stage-1 solution: map each order to its workstation and each (item, order) to its pod
    z1_sol = model1.getAttr(gb.GRB.Attr.X, z1)
    x1_sol = model1.getAttr(gb.GRB.Attr.X, x1)

    orders_by_workstation = [[] for _ in range(n_w)]
    pod_of_item = {}  # (sku, order_idx) -> pod_idx

    for m in range(n_orders):
        for w in range(n_w):
            if z1_sol[m, w] > 0.5:
                orders_by_workstation[w].append(m)
                break
        for i in orders_items[m]:
            for p in OptManager.pod_indices_by_sku[i]:
                if x1_sol[i, m, p] > 0.5:
                    pod_of_item[(i, m)] = p
                    break



    ### STAGE 2: SCHEDULING 

    logging.info("Building second stage model ...")
    model2 = gb.Model('Scheduling')

    # x2[i,m,t] = 1 if item i of order m has been picked by time t (cumulative)
    # y2[p,a]   = 1 if pod p traverses arc a in the time-space network
    # v2[m,t]   = 1 if order m is actively being picked at time t
    # f2[m,t]   = 1 if all items of order m are ready by t (triggers opening)
    # g2[m,t]   = 1 if order m completes at t (all items picked simultaneously)
    x2 = model2.addVars(OptManager.n_skus, n_orders, OptManager.N_TIME, vtype=gb.GRB.BINARY)
    y2 = model2.addVars(n_p, n_a,                                        vtype=gb.GRB.BINARY)
    v2 = model2.addVars(n_orders, OptManager.N_TIME,                     vtype=gb.GRB.BINARY)
    f2 = model2.addVars(n_orders, OptManager.N_TIME,                     vtype=gb.GRB.BINARY)
    g2 = model2.addVars(n_orders, OptManager.N_TIME,                     vtype=gb.GRB.BINARY)

    for w in range(n_w):
        w_pos = state.warehouse.workstations[w].position
        for t in range(OptManager.N_TIME):
            # EC13: workstation throughput cap — at most CAP_WS orders picked simultaneously
            model2.addLConstr(
                gb.quicksum(v2[m, t] for m in orders_by_workstation[w]),
                gb.GRB.LESS_EQUAL, OptManager.CAP_WS, name='EC13')

            # EC14: time capacity — item picks and pod arrivals must fit within TIME_UNIT
            if t > 0:
                item_work = gb.quicksum(
                    OptManager.DELTA_ITEM * (x2[i, m, t] - x2[i, m, t - 1])
                    for m in orders_by_workstation[w]
                    for i in orders_items[m])
                pod_arrivals = gb.quicksum(
                    OptManager.DELTA_POD * y2[p, a]
                    for p in range(n_p)
                    for a in OptManager.incoming_arc_idx[(w_pos, t)]
                    if a < len(OptManager.travelling_arcs))
                model2.addLConstr(
                    item_work + pod_arrivals,
                    gb.GRB.LESS_EQUAL, OptManager.TIME_UNIT, name='EC14')

    for p in range(n_p):
        # EC15: flow conservation at t=0 — each pod departs from its storage location
        model2.addLConstr(
            gb.quicksum(y2[p, a] for a in OptManager.outgoing_arc_idx[
                (state.warehouse.pods[p].storage_location, 0)]),
            gb.GRB.EQUAL, 1, name=f'EC15_pod{p}_iniz')

        # EC16: flow conservation at intermediate nodes (pod cannot appear or vanish)
        for node in OptManager.nodes:
            if node[1] in (0, OptManager.N_TIME - 1):
                continue
            model2.addLConstr(
                gb.quicksum(y2[p, a] for a in OptManager.incoming_arc_idx[node])
                - gb.quicksum(y2[p, a] for a in OptManager.outgoing_arc_idx[node]),
                gb.GRB.EQUAL, 0, name=f'EC16_pod{p}_nodo{node}')

    # TODO: add congestion constraints

    for w in range(n_w):
        w_pos = state.warehouse.workstations[w].position
        for m in orders_by_workstation[w]:
            for i in orders_items[m]:
                p = pod_of_item[(i, m)]
                # EC18: item cannot be picked at t=0; pick only after pod arrives at workstation
                model2.addLConstr(x2[i, m, 0], gb.GRB.EQUAL, 0, name='EC18')
                for t in range(1, OptManager.N_TIME):
                    model2.addLConstr(
                        x2[i, m, t] - x2[i, m, t - 1],
                        gb.GRB.LESS_EQUAL,
                        gb.quicksum(y2[p, a] for a in OptManager.incoming_arc_idx[(w_pos, t)]),
                        name='EC18')

    for m in range(n_orders):
        for t in range(OptManager.N_TIME):
            for i in orders_items[m]:
                if t > 0:
                    # EC19: x2 is non-decreasing (once picked, stays picked)
                    model2.addLConstr(x2[i, m, t] >= x2[i, m, t - 1], name='EC19')
                    model2.addLConstr(v2[m, t] <= x2[i, m, t],          name='picking_only_if_m_open')
                    model2.addLConstr(v2[m, t] >= v2[m, t - 1] - g2[m, t], name='continuity_of_v2')

                # EC21/EC22: link f2 and g2 to item completion status
                model2.addLConstr(f2[m, t] >= x2[i, m, t], name='EC21')
                model2.addLConstr(g2[m, t] <= x2[i, m, t], name='EC22')

            # EC20: v2 = f2 - g2 (order is active iff started but not yet complete)
            model2.addLConstr(v2[m, t] == f2[m, t] - g2[m, t], name='EC20')
            # Lower bound on g2: order completes only when all items are picked
            model2.addLConstr(
                g2[m, t] >= gb.quicksum(x2[i, m, t] for i in orders_items[m]) - (len(orders_items[m]) - 1),
                name='g_LowerB')

            # Fix v2[m,0]=1 for orders already open (not yet closed by active tasks)
            if orders[m].order_id in state.warehouse.workstations[w].opened_orders:
                model2.addLConstr(v2[m, 0] == 1, name='InitialCond')

    # Maximize items picked by the end of the horizon
    model2.setObjective(
        gb.quicksum(x2[i, m, OptManager.N_TIME - 1]
                    for m in range(n_orders)
                    for i in orders_items[m]),
        sense=gb.GRB.MAXIMIZE)
    model2.setParam('MIPGap', 0.20)
    model2.setParam('ImproveStartGap', 0.25)

    logging.info('Model2 built. Solving ...')
    model2.optimize()
    logging.info("Model2 solved. Status %s   [2: OPTIMAL, 3: INFEASIBLE, 9: TIME LIMIT]",
                 model2.Status)

    if model2.Status == gb.GRB.INFEASIBLE:
        model2.computeIIS()
        model2.write("is.ilp")

    x2_sol = model2.getAttr(gb.GRB.Attr.X, x2)
    v2_sol = model2.getAttr(gb.GRB.Attr.X, v2)
    y2_sol = model2.getAttr(gb.GRB.Attr.X, y2)
    return orders, z1_sol, x1_sol, x2_sol, v2_sol