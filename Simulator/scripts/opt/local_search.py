import numpy as np
import copy

def check_constraints():
    pass

def compute_objective():
    pass

def build_solution(x, orders, map_im2touple, all_arcs, map_im2pod):

    # Look-ups 
    im_by_orders = {}
    for im, (i,m) in map_im2touple.items():
        if m in im_by_orders.keys():
            im_by_orders[m].append(im)
        else:
            im_by_orders[m] = [im]
        
    from_RelPod_to_PodId = list(set(map_im2pod.values()))
    from_PodId_to_RelPod = {id_p:rel_p for rel_p, id_p in enumerate(from_RelPod_to_PodId)}


    # Building f[m,t] = 1 if at least 1 item of order m is picked by time t
    # Building g[m,t] = 1 if all items of order m are picked by time t-1
    first_one_idx = (x == 0).sum(axis=1)
  
    f = np.zeros((len(orders), x.shape[1]))
    g = np.zeros((len(orders), x.shape[1]))

    for m in range(len(orders)):
        taus = [first_one_idx[im] for im in im_by_orders[m]]
        t_start = min(taus)
        t_end = max(taus) +1
        f[m, t_start:] = 1
        g[m, t_end:] = 1

    # Building v[m,t] = f[m,t] - g[m,t]
    v = f-g

    # Building y[p,a] = 1 if pod p is in arc a
    y = np.zeros((len(from_RelPod_to_PodId), len(all_arcs)))
    ### TODO

    return x, f, g, v, y


def evaluate_x_perturbated(x, orders, map_im2touple, all_arcs, map_im2pod):

    sol = build_solution(x, orders, map_im2touple, all_arcs, map_im2pod)
    # sol = [x, f, g, v, y]

    if check_constraints:
        obj = compute_objective()
    else: 
        obj = None

    return obj, sol


def local_search(OptManager, orders, map_im2touple, orders_by_workstation, map_im2pod):

    """
    Local search only for the second stage problem
    So orders_by_workstation and pod_of_item are decisions already made
    """

    rng = np.random.default_rng(seed=42) # local random generator for local search
    am_I_stuck = False


    ### BUILDING INITIAL SOLUTION

    # TODO



    best_sol = None
    best_sol_obj = - np.inf
    
    while not am_I_stuck:

        best_x_perturb = None

        ### SCANNING A NEIGHBORHOOD

        # Finding first 1 for each row (if there is)
        first_one_idx = (x_solution == 0).sum(axis=1)

        # 1. Trying to anticipate picking by 1 time unit
        for id_row in range(x_solution.shape[0]):
            if first_one[id_row] > 0:
                x_perturbated = x_solution.copy()
                x_perturbated[id_row, first_one_idx[id_row]-1] = 1

                 # Evaluating neighbour
                obj, sol = evaluate_x_perturbated(x_perturbated, orders, map_im2touple, OptManager.all_arcs, map_im2pod)
                if obj > best_sol_obj:
                    best_sol_obj, best_sol, best_x_perturb = obj, sol, x_perturbated

        # 2. Swapping the picking of two orders of the same workstation

        # Look-ups
        im_by_orders = {}
        for im, (i,m) in map_im2touple.items():
            if m in im_by_orders.keys():
                im_by_orders[m].append(im)
            else:
                im_by_orders[m] = [im]

        map_touple2im = {(i,m): im for im, (i,m) in map_im2touple.items()}

        for ws_id in orders_by_workstation.keys():
            list_ord = list(orders_by_workstation[ws_id])
            for id_1, m1 in enumerate(list_ord):
                for m2 in list_ord[id_1+1:]:
                    min_t_m1 = min([first_one_idx[im] for im in im_by_orders[m1]])
                    max_t_m1 = max([first_one_idx[im] for im in im_by_orders[m1]])
                    min_t_m2 = min([first_one_idx[im] for im in im_by_orders[m2]])
                    max_t_m2 = max([first_one_idx[im] for im in im_by_orders[m2]])

                    for _ in range(5):
                        x_perturbated = x_solution.copy()
                        for im in im_by_orders[m1]:
                            first_one = rng.integers(min_t_m1-1, max_t_m1+2)
                            x_perturbated[im, :first_one] = 0
                            x_perturbated[im, first_one:] = 1

                        for im in im_by_orders[m2]:
                            first_one = rng.integers(min_t_m2-1, max_t_m2+2)
                            x_perturbated[im, :first_one] = 0
                            x_perturbated[im, first_one:] = 1
                        
                        # Evaluating neighbour
                        obj, sol = evaluate_x_perturbated(x_perturbated, orders, map_im2touple, OptManager.all_arcs, map_im2pod)
                        if obj > best_sol_obj:
                            best_sol_obj, best_sol, best_x_perturb = obj, sol, x_perturbated


        x_solution = best_x_perturb
        if best_x_perturb is None:
            am_I_stuck = True

