from Simulator.scripts.core.entities import Task, Visit
from Simulator.scripts.core.enums import PodStatus, RobotStatus

def assign_order_to_workstation_policy(order, workstations) -> int:
    """
    Assign an order to the workstation with the shortest order queue.

    Parameters
    ----------
    order : Order                    The order to be assigned.
    workstations : list[Workstation] List of available workstations.

    Returns
    -------
    int  workstation_id of the selected workstation.
    """
    return min(workstations, key=lambda ws: len(ws.order_buffer) + len(ws.opened_orders)).workstation_id



def design_tasks_for_ws(workstation, warehouse, arrived_orders, task_counter) -> list[Task]:
    """
    Select the best pods to send to a workstation using a greedy set cover approach.

    Iteratively selects the idle pod that covers the most uncovered SKUs
    across all open orders at the workstation (pile-on maximization).
    Ties are broken by Manhattan distance to the workstation.
    At most podqueue_capacity pods are selected.

    Each time a pod is selected, its SKUs are removed from the uncovered
    pool, avoiding redundant deliveries. A single Visit per pod groups
    all contributing orders and their SKUs together.

    Parameters
    ----------
    workstation : Workstation       Target workstation.
    warehouse : Warehouse           Full warehouse state.
    arrived_orders : PriorityQueue  All arrived orders (for SKU lookup).
    task_counter : int              Current task ID counter (incremented externally).

    Returns
    -------
    list[Task]  Tasks to release, one per selected pod, sorted by selection order.
    """

    # Collect uncovered SKUs across all open orders
    remaining_skus = set()
    for order_id in workstation.opened_orders:
        order = arrived_orders.get(order_id)
        if order is not None:
            remaining_skus.update(order.items_pending)

    if not remaining_skus:
        return []

    # Greedy set cover
    already_selected = set()
    for v in workstation.active_tasks:
        already_selected.add(v.items)

    tasks = []

    while len(tasks) < workstation.workload_capacity - len(workstation.active_tasks) and remaining_skus:

        best_pod, best_score, best_dist = None, 0, float('inf')

        for pod in warehouse.pods:
            if pod.pod_id in already_selected:
                continue

            pile_on = len(set(pod.items) & remaining_skus)
            if pile_on == 0:
                continue

            distance = warehouse.manhattan_distance(pod.storage_location, workstation.position)

            if pile_on > best_score or (pile_on == best_score and distance < best_dist):
                best_pod, best_score, best_dist = pod, pile_on, distance

        if best_pod is None:
            break

        # Build single Visit grouping all contributing orders
        contributing_orders = []
        skus_for_visit = []
        for order_id in workstation.opened_orders:
            order = arrived_orders.get(order_id)
            if order is None:
                continue
            skus_for_order = [s for s in best_pod.items if s in set(order.items_pending)]
            if skus_for_order:
                contributing_orders.append(order_id)
                skus_for_visit.extend(skus_for_order)

        tasks.append(Task(
            task_id=task_counter + len(tasks),
            pod_id=best_pod.pod_id,
            stops=[Visit(
                workstation_id=workstation.workstation_id,
                orders=contributing_orders,
                items=skus_for_visit
            )],
            priority=task_counter + len(tasks),
        ))

        already_selected.add(best_pod.pod_id)
        remaining_skus -= set(best_pod.items)

    return tasks



def get_nearest_idle_robot(pod, warehouse) -> int | None:
    """
    Return the robot_id of the nearest idle robot to a given pod.

    Ties are broken by robot_id. Returns None if no idle robot is available.

    Parameters
    ----------
    pod : Pod             Target pod.
    warehouse : Warehouse Full warehouse state.

    Returns
    -------
    int | None  robot_id of the nearest idle robot, or None if none available.
    """
    best_robot, best_dist = None, float('inf')

    for robot in warehouse.robots:
        if robot.status == RobotStatus.IDLE:
            dist = warehouse.manhattan_distance(robot.position, pod.storage_location)
            if dist < best_dist or (dist == best_dist and robot.robot_id < best_robot.robot_id):
                best_robot, best_dist = robot, dist

    return best_robot.robot_id if best_robot is not None else None