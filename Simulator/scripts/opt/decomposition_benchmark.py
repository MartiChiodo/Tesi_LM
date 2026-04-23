import logging
import gurobipy as gb

def solve_by_decomposition(OptManager, sim, state):

    orders, orders_items = OptManager._extract_orders(state)
    n_orders = len(orders)

    if n_orders == 0:
        logging.debug("[OptManager] No orders to optimise — skipping model build.")
        model = None
        return

    n_p  = OptManager.n_pods
    n_w  = OptManager.n_workstations
    n_a  = len(OptManager.all_arcs)

    ### ORDER-WORKSTATION and ORDER-ITEM-POD ASSIGNMENT

    logging.info("Building first stage problem ... ")
    model1 = gb.Model('OW_OIP_Assignments')


    # Variables
    z1 = model1.addVars(n_orders, n_w,
                       vtype = gb.GRB.BINARY, )
    x1 = model1.addVars(OptManager.n_skus, n_orders, n_p,
                        vtype = gb.GRB.BINARY)
    
    y1 = model1.addVars(n_w, n_p,
                        vtype = gb.GRB.BINARY)
    
    # Costraints

    for m in range(n_orders):
        model1.addLConstr(
            gb.quicksum(z1[m,w] for w in range(n_w)),
            gb.GRB.EQUAL, 1,
            name='EC7')
        
    for m in range(n_orders):
        for i in orders_items[m]:
            model1.addLConstr(
                gb.quicksum(x1[i,m,p] for p in OptManager.pod_indices_by_sku[i]),
                gb.GRB.EQUAL, 1,
                name = 'EC8')
            
        for w in range(n_w):
            for i in orders_items[m]:
                for p in OptManager.pod_indices_by_sku[i]:
                    model1.addLConstr(
                        y1[w,p],
                        gb.GRB.GREATER_EQUAL,
                        x1[i,m,p] + z1[m,w] -1,
                        name = 'EC10'
                    )
              
    lower_I = sum([len(i) for i in orders_items]) * 1/10
    upper_I = sum([len(i) for i in orders_items]) * 9/10
    for w in range(n_w):
        model1.addLConstr(
            gb.quicksum(z1[m,w]*len(orders_items[m]) for m in range(n_orders)),
            gb.GRB.LESS_EQUAL, upper_I,
            name = 'EC11_upper')
        model1.addLConstr(
            gb.quicksum(z1[m,w]*len(orders_items[m]) for m in range(n_orders)),
            gb.GRB.GREATER_EQUAL, lower_I,
            name = 'EC11_lower')
        
    for w in range(n_w):
        for id_o in state.warehouse.workstations[w].opened_orders:
            m = next((i for i, o in enumerate(orders) if o.order_id == id_o), None)
            model1.addLConstr(
                z1[m, w] == 1,
                name = 'InitialCond'
            )
        
    
    # Objective
    model1.setObjective(
            gb.quicksum(y1[w,p]
                        for w in range(n_w)
                        for p in range(n_p)),
            sense = gb.GRB.MINIMIZE
        )
                             
    logging.info("Model1 built. Solving model ...")

    model1.optimize()
    logging.info("Model1 solved. Status %s   [2: OPTIMAL, 3: INFEASIBLE, 9:TIME LIMIT]",
                model1.Status)
    
    if model1.Status == gb.GRB.INFEASIBLE:
        model1.computeIIS()
        model1.write("scripts/opt/iis.ilp")


    # From solution of model1 to input to model2
    z1_sol = model1.getAttr(gb.GRB.Attr.X, z1)
    orders_by_workstation = [[] for _ in range(n_w)]
    x1_sol = model1.getAttr(gb.GRB.Attr.X, x1)
    pod_of_item = {}
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




    ### SCHEDULING
    logging.info("Building second stage model ... ")
    model2 = gb.Model('Scheduling')

    # Variables
    x2 = model2.addVars(OptManager.n_skus, n_orders, OptManager.N_TIME,
                        vtype=gb.GRB.BINARY)
    y2 = model2.addVars(n_p, n_a,
                        vtype=gb.GRB.BINARY)
    v2 = model2.addVars(n_orders, OptManager.N_TIME,
                        vtype=gb.GRB.BINARY)
    
    f2 = model2.addVars(n_orders, OptManager.N_TIME,
                        vtype=gb.GRB.BINARY)
    g2 = model2.addVars(n_orders, OptManager.N_TIME,
                        vtype=gb.GRB.BINARY)

    # Constraints
    for w in range(n_w):
        w_pos = state.warehouse.workstations[w].position
        for t in range(OptManager.N_TIME):
            model2.addLConstr(
                gb.quicksum(v2[m,t] for m in orders_by_workstation[w]),
                gb.GRB.LESS_EQUAL, OptManager.CAP_WS,
                name = 'EC13'
            )

            if t > 0:
                model2.addLConstr(
                    gb.quicksum(OptManager.DELTA_ITEM * (x2[i,m,t] -x2[i,m,t-1]) for m in orders_by_workstation[w] for i in orders_items[m])
                    + gb.quicksum(OptManager.DELTA_POD * y2[p,a] for p in range(n_p) for a in OptManager.incoming_arc_idx[(w_pos,t)] if a < len(OptManager.travelling_arcs)),
                    gb.GRB.LESS_EQUAL, OptManager.TIME_UNIT,
                    name = 'EC14'
                )               

    for p in range(n_p):
        model2.addLConstr(
            gb.quicksum(y2[p,a] for a in OptManager.outgoing_arc_idx[(state.warehouse.pods[p].storage_location, 0)]),
            gb.GRB.EQUAL, 1,
            name = f'EC15_pod{p}_iniz'
        )

        for node in OptManager.nodes:
            if node[1] == OptManager.N_TIME -1 or node[1] == 0:
                continue
            else:
                model2.addLConstr(
                    gb.quicksum(y2[p,a] for a in OptManager.incoming_arc_idx[node]) 
                    - gb.quicksum(y2[p,a] for a in OptManager.outgoing_arc_idx[node]),
                    gb.GRB.EQUAL, 0,
                    name = f'EC16_pod{p}_nodo{node}'
                )

    # TODO : congestion constr

    for w in range(n_w): # n_w is small
        w_pos = state.warehouse.workstations[w].position
        for m in orders_by_workstation[w]:
            for i in orders_items[m]:
                p = pod_of_item[(i,m)]
                model2.addLConstr(
                        (x2[i,m,0]),
                        gb.GRB.EQUAL, 0,
                        name= 'EC18'
                    ) 
                for t in range(1, OptManager.N_TIME):
                    model2.addLConstr(
                        (x2[i,m,t] - x2[i,m,t-1]),
                        gb.GRB.LESS_EQUAL,
                        gb.quicksum(y2[p,a] for a in OptManager.incoming_arc_idx[(w_pos,t)]),
                        name= 'EC18'
                    )

    for m in range(n_orders):
        for t in range(OptManager.N_TIME):
            for i in orders_items[m]:
                if t > 0:
                    model2.addLConstr(x2[i,m,t] >= x2[i,m,t-1], name = 'EC19')
                    model2.addLConstr(v2[m,t] <= x2[i,m,t], name = 'picking_only_if_m_open')
                    model2.addLConstr(v2[m,t] >= v2[m,t-1] - g2[m,t], name = 'continuity_of_v2')
                    
                model2.addLConstr(f2[m,t] >= x2[i,m,t], name = 'EC21')
                model2.addLConstr(g2[m,t] <= x2[i,m,t], name = 'EC22')
            model2.addLConstr(v2[m,t] == f2[m,t] - g2[m,t], name = 'EC20')
            model2.addLConstr(g2[m,t] >= \
                              gb.quicksum(x2[i,m,t] for i in orders_items[m]) - (len(orders_items[m])-1),
                             name = 'g_LowerB')
            
            if orders[m].order_id in state.warehouse.workstations[w].opened_orders:
                # I impose initial condition only for opened orders that won't be closed by already active tasks
                model2.addLConstr(
                    v2[m, 0] == 1,
                    name = 'InitialCond'
                )                
    
    # Objective
    model2.setObjective(
        gb.quicksum(x2[i,m,OptManager.N_TIME-1] for m in range(n_orders) for i in orders_items[m])
        # + gb.quicksum(v2[m,OptManager.N_TIME-1] for m in range(n_orders))
        , sense = gb.GRB.MAXIMIZE
    )


    logging.info('Model2 built. Solving ... ')

    """ # ── DIAGNOSTICS ───────────────────────────────────────────────────────────────

    # 1. Per ogni pod, quanti archi escono da storage a t=0?
    for p in range(n_p):
        loc = state.warehouse.pods[p].storage_location
        out_arcs = OptManager.outgoing_arc_idx.get((loc, 0), [])
        print(f"  pod={p} storage={loc} outgoing_arcs_t0={len(out_arcs)}")

    # 2. Per ogni workstation e ogni t, quanti archi in entrata esistono?
    for w in range(n_w):
        w_pos = state.warehouse.workstations[w].position
        arrivals = [(t, len(OptManager.incoming_arc_idx.get((w_pos,t), []))) 
                    for t in range(OptManager.N_TIME) 
                    if len(OptManager.incoming_arc_idx.get((w_pos,t), [])) > 0]
        print(f"  ws={w} first_arrival_t={arrivals[0] if arrivals else 'NEVER'} total_slots={len(arrivals)}")

    # 3. Quanti ordini aperti hanno la condizione iniziale v2[m,0]=1?
    n_initial = sum(len(state.warehouse.workstations[w].opened_orders) for w in range(n_w))
    print(f"  orders with v2[m,0]=1: {n_initial}")

    # 4. N_TIME e TIME_UNIT
    print(f"  N_TIME={OptManager.N_TIME}, TIME_UNIT={OptManager.TIME_UNIT}")
    print(f"  total_time_horizon={OptManager.N_TIME * OptManager.TIME_UNIT:.1f}s") """

    model2.optimize()
    logging.info("Model2 solved. Status %s   [2: OPTIMAL, 3: INFEASIBLE, 9:TIME LIMIT]",
            model2.Status)
    
    if model2.Status == gb.GRB.INFEASIBLE:
        model2.computeIIS()
        model2.write("is.ilp")


    # I return all the variable necessary to design tasks: z_sol, x1_sol, x2_sol, v_sol
    x2_sol = model2.getAttr(gb.GRB.Attr.X, x2)
    v2_sol = model2.getAttr(gb.GRB.Attr.X, v2)
    y2_sol = model2.getAttr(gb.GRB.Attr.X, y2)
    return orders, z1_sol, x1_sol, x2_sol, v2_sol