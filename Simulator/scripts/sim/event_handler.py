"""
Event handlers for the warehouse simulator.

This module implements the discrete-event simulation event processing functions.
Each handler receives an Event and the Simulator state, updates the state, and
schedules future events.
"""

import logging
from Simulator.scripts.core.entities import Order, Event, Task, Visit
from Simulator.scripts.core.warehouse import Warehouse
from Simulator.scripts.core.enums import OrderStatus, RobotStatus, PodStatus, WorkstationPickingStatus, EventType
from Simulator.scripts.opt.policies import assign_order_to_workstation_policy, design_tasks_for_ws, get_nearest_idle_robot
from Simulator.scripts.sim.utils import sample_sku
from Simulator.scripts.opt.exact_optimization import *


def arrival_order(event: Event, sim) -> None:
    """
    Handle a new customer order arrival.

    Generates an order following Barnhart et al. 2024: single-item with
    probability p, otherwise geometric(p) + 2 items. Adds the order to
    the system backlog and schedules the next order arrival.

    If optimization is disabled, immediately assigns the order to the
    least-loaded workstation and opens it if a slot is available.
    """
    assert len(sim.order_gen_config) == 3, (
        f"order_gen_config must have 3 elements (interarrival, p_single, p_geo), "
        f"got {len(sim.order_gen_config)}"
    )

    order_id = sim.orders_counter
    sim.orders_counter += 1

    rnd = sim.RANDOM_GENERATOR.random()
    if rnd < sim.order_gen_config[1]:
        order_size = 1
    else:
        order_size = sim.RANDOM_GENERATOR.geometric(p=sim.order_gen_config[2]) + 2

    sku_list = [
        sample_sku(sim.RANDOM_GENERATOR, sim.warehouse_status.num_skus)
        for _ in range(order_size)
    ]

    o = Order(
        order_id=order_id,
        arrival_time=sim.current_time,
        order_size=order_size,
        items_required=set(sku_list),
        items_pending=set(sku_list),
        workstation_id=None,
        status=OrderStatus.BACKLOG
    )
    sim.orders_in_system.push(o)

    logging.debug("Order %i arrived: items_required = %s.     [orders_in_system = %i]",
                 order_id, sku_list, sim.orders_counter - _count_closed(sim))

    # Schedule next arrival
    interarrival_time = sim.order_gen_config[0]
    sim.future_events.push(Event(
        time=sim.current_time + interarrival_time,
        type=EventType.ARRIVAL_ORDER
    ))

    if not sim.optimization_enabled:
        workstation_id = assign_order_to_workstation_policy(
            o,
            sim.warehouse_status.workstations
        )
        workstation = sim.warehouse_status.get_workstation(workstation_id)
        o.workstation_id = workstation_id
        o.status = OrderStatus.WAITING

        if workstation.has_open_slot():
            sim.future_events.push(Event(
                time=sim.current_time,
                type=EventType.OPEN_ORDER,
                info=o
            ))
        else:
            workstation.order_buffer.append(order_id)
            logging.debug("Order queued at workstation %i.   [order_queue len = %i]",
                         workstation_id, len(workstation.order_buffer))


def open_order(event: Event, sim) -> None:
    """
    Open an order at its assigned workstation.

    Transitions the order from WAITING to OPEN status and registers it
    in the workstation's active orders. If optimization is disabled,
    immediately designs tasks to fetch pods matching the order SKUs.
    """
    o = event.info

    if o.workstation_id is None:
        raise ValueError(f"Cannot open order {o.order_id}: no workstation assigned")

    assert o.status == OrderStatus.WAITING, (
        f"Order {o.order_id} state transition error: expected WAITING, got {o.status.name}"
    )

    workstation = sim.warehouse_status.get_workstation(o.workstation_id)

    assert len(workstation.opened_orders) < workstation.order_capacity, (
        f"Workstation {o.workstation_id} is at full capacity "
        f"({workstation.order_capacity}) but trying to open order {o.order_id}"
    )

    o.status = OrderStatus.OPEN
    workstation.opened_orders.add(o.order_id)

    sim.STAT_MANAGER.update_statistic(
        type='WS_AVG_OO',
        info=[workstation.workstation_id, len(workstation.opened_orders), sim.current_time]
    )

    logging.debug("Order %i (skus required = %s) opened at workstation %i.   [open_orders = %i/%i]",
                 o.order_id, o.items_required, o.workstation_id,
                 len(workstation.opened_orders), workstation.order_capacity)

    if not sim.optimization_enabled:
        tasks, sim.task_counter = design_tasks_for_ws(
            workstation=workstation,
            warehouse=sim.warehouse_status,
            orders_in_system=sim.orders_in_system,
            task_counter=sim.task_counter,
            active_tasks=sim.active_tasks
        )

        if tasks:
            total_items = sum(len(t.stops[0].items) for t in tasks)
            logging.debug("%i task(s) designed covering %i sku(s) required", len(tasks), total_items)
            for t in tasks:
                sim.future_events.push(Event(
                    time=sim.current_time,
                    type=EventType.RELEASE_TASK,
                    info=t
                ))
        else:
            logging.debug("No tasks designed (all SKUs already covered)")

    else:
        available_capacity = workstation.released_task_capacity - workstation.counter_released_task
        for _ in range(available_capacity):
            sim.future_events.push(Event(
                time=sim.current_time,
                type=EventType.RELEASE_TASK,
                info=o.workstation_id
            ))


def release_task(event: Event, sim) -> None:
    """
    Release a task to the execution queue.

    Moves a task from scheduled_tasks or event payload to released_tasks,
    making it eligible for execution by an idle robot. Immediately triggers
    START_TASK if an idle robot is available.
    """
    if sim.optimization_enabled:
        workstation_id = event.info
        workstation = sim.warehouse_status.get_workstation(workstation_id)
        if not workstation.can_release_task() or sim.scheduled_tasks[workstation_id].is_empty():
            return
        task = sim.scheduled_tasks[workstation_id].pop()
    else:
        task = event.info
        workstation_id = task.stops[0].workstation_id

    assert task is not None, "release_task: task is None after retrieval"

    # update() overwrites if already present, push() if new
    if sim.released_tasks.get(task.task_id) is not None:
        sim.released_tasks.update(task)
    else:
        sim.released_tasks.push(task)

    ws_list = []
    for visit in task.stops:
        ws = sim.warehouse_status.get_workstation(visit.workstation_id)
        ws.released_tasks.add(task.task_id)
        ws_list.append(visit.workstation_id)

    logging.debug("Task %i released: pod %i required by workstation(s) %s.  [number of released tasks = %i]",
                 task.task_id, task.pod_id, ws_list, len(sim.released_tasks))

    has_idle_robot = any(r.status == RobotStatus.IDLE for r in sim.warehouse_status.robots)
    if has_idle_robot:
        sim.future_events.push(Event(time=sim.current_time, type=EventType.START_TASK))


def start_task(event: Event, sim) -> None:
    """
    Start executing a task with the nearest idle robot.

    Assigns the highest-priority released task to the nearest idle robot.
    Skips tasks whose pod is currently BUSY, re-queuing them for later.
    Updates pod and robot status to BUSY, registers visits as active,
    and schedules pod arrival at the first workstation.
    """
    if sim.released_tasks.is_empty():
        return

    # Find the highest-priority task whose pod is IDLE
    # Tasks with BUSY pods are temporarily set aside and re-pushed afterward
    skipped_t  = []
    task = None

    while not sim.released_tasks.is_empty():
        candidate = sim.released_tasks.pop()
        pod = sim.warehouse_status.get_pod(candidate.pod_id)
        if pod.status == PodStatus.IDLE:
            task = candidate
            break
        logging.debug("Task %i blocked: pod %i not idle.     [number of released tasks = %i]",
                     candidate.task_id, candidate.pod_id, len(sim.released_tasks))
        skipped_t.append(candidate)

    for t in skipped_t:
        sim.released_tasks.push(t)

    if task is None:
        return  # all released tasks have busy pods

    pod = sim.warehouse_status.get_pod(task.pod_id)
    assert pod.status == PodStatus.IDLE, f"Pod {task.pod_id} should be IDLE before task start"

    robot_id = get_nearest_idle_robot(pod, sim.warehouse_status)
    if robot_id is None:
        logging.debug("Task %i blocked: no idle robots.", task.task_id)
        sim.released_tasks.push(task)  # re-queue: will retry on next RETURN_POD
        return

    robot = sim.warehouse_status.get_robot(robot_id)
    assert robot.status == RobotStatus.IDLE, f"Robot {robot_id} should be IDLE before task start"

    # Commit state changes
    sim.active_tasks[task.task_id] = task
    pod.status = PodStatus.BUSY
    robot.status = RobotStatus.BUSY
    task.robot_id = robot_id

    sim.STAT_MANAGER.update_statistic(type='RB_FREQ', info=[robot.robot_id, RobotStatus.BUSY, sim.current_time])

    for visit in task.stops:
        ws = sim.warehouse_status.get_workstation(visit.workstation_id)
        ws.active_tasks.add(task.task_id)
        ws.released_tasks.discard(task.task_id)

    first_visit = task.stops[0]
    first_workstation = sim.warehouse_status.get_workstation(first_visit.workstation_id)
    travel_time = sim.warehouse_status.travel_time(
        sim.warehouse_status.cell2coord(pod.storage_location),
        sim.warehouse_status.cell2coord(first_workstation.position),
        sim.RANDOM_GENERATOR
    )
    sim.future_events.push(Event(
        time=sim.current_time + travel_time,
        type=EventType.ARRIVAL_POD_WST,
        info=task
    ))

    idle_robots = sum(1 for r in sim.warehouse_status.robots if r.status == RobotStatus.IDLE)
    logging.debug("Task %i started: robot %i allocated to pod %i. Currently heading to workstation %i (arrival = %f sec).   [idle_robots = %i/%i]",
                 task.task_id, task.robot_id, task.pod_id, first_visit.workstation_id, sim.current_time + travel_time,
                 idle_robots, len(sim.warehouse_status.robots))


def arrival_pod_wst(event: Event, sim) -> None:
    """
    Handle pod arrival at a workstation.

    Updates robot position and checks if the workstation is idle.
    If idle, immediately starts picking; otherwise, queues the pod.
    """
    task = event.info
    current_visit = task.stops[0]
    workstation = sim.warehouse_status.get_workstation(current_visit.workstation_id)
    robot = sim.warehouse_status.get_robot(task.robot_id)

    assert robot.status == RobotStatus.BUSY, (
        f"Robot {task.robot_id} should be BUSY on pod arrival, got {robot.status.name}"
    )

    robot.position = workstation.position

    logging.debug("Pod %i arrived at workstation %i - currently workstation status = %s",
                 task.pod_id, current_visit.workstation_id, workstation.status.name)

    if workstation.status == WorkstationPickingStatus.IDLE:
        sim.future_events.push(Event(
            time=sim.current_time,
            type=EventType.START_PICKING,
            info=task
        ))
    else:
        workstation.picking_buffer.append(task.task_id)
        logging.debug("Pod queued at workstation.    [picking_buffer of workstation = %s]",
                     workstation.picking_buffer)


def start_picking(event: Event, sim) -> None:
    """
    Start picking items from an arrived pod.

    Sets workstation status to BUSY and schedules picking completion
    based on the number of items at this visit.
    """
    task = event.info
    visit = task.stops[0]
    workstation = sim.warehouse_status.get_workstation(visit.workstation_id)

    assert workstation.status == WorkstationPickingStatus.IDLE, (
        f"Workstation {visit.workstation_id} should be IDLE before picking, "
        f"got {workstation.status.name}"
    )
    assert task.task_id in sim.active_tasks, (
        f"Task {task.task_id} not found in active_tasks at start_picking"
    )

    workstation.status = WorkstationPickingStatus.BUSY
    sim.STAT_MANAGER.update_statistic(
        type='WS_FREQ',
        info=[workstation.workstation_id, WorkstationPickingStatus.BUSY, sim.current_time]
    )

    logging.debug("Processing task %i at workstation %i: picking items %s",
                 task.task_id, visit.workstation_id, visit.items)

    picking_time = workstation.estimated_picking_time(len(visit.items))
    sim.future_events.push(Event(
        time=sim.current_time + picking_time,
        type=EventType.END_PICKING,
        info=task
    ))


def end_picking(event: Event, sim) -> None:
    """
    Handle picking completion at a workstation.

    Drains the picking buffer first (unconditionally), then schedules the
    pod's next stop or return to storage. Finally updates order states and
    closes any completed orders. Task redesign is skipped if any order closed
    (the close_order handler will open a new one and trigger redesign).
    """
    task = event.info
    completed_visit = task.stops[0]
    workstation = sim.warehouse_status.get_workstation(completed_visit.workstation_id)

    assert workstation.status == WorkstationPickingStatus.BUSY, (
        f"Workstation {completed_visit.workstation_id} should be BUSY at end_picking, "
        f"got {workstation.status.name}"
    )

    workstation.status = WorkstationPickingStatus.IDLE
    workstation.active_tasks.discard(task.task_id)

    sim.STAT_MANAGER.update_statistic(
        type='WS_FREQ',
        info=[workstation.workstation_id, WorkstationPickingStatus.IDLE, sim.current_time]
    )

    logging.debug("Ended picking operation for orders %s at workstation %i.    [picking_buffer len = %s]",
                 completed_visit.orders, completed_visit.workstation_id, workstation.picking_buffer)

    task.stops.pop(0)

    # ── Always drain picking buffer first ────────────────────────────────────
    if workstation.picking_buffer:
        next_task_id = workstation.picking_buffer.pop(0)
        next_task = sim.active_tasks.get(next_task_id)
        assert next_task is not None, (
            f"Task {next_task_id} in picking_buffer but not in active_tasks"
        )
        sim.future_events.push(Event(
            time=sim.current_time,
            type=EventType.START_PICKING,
            info=next_task
        ))
        logging.debug("Dequeued task %i from picking buffer at workstation %i.   [picking_buffer len = %i]",
                     next_task_id, workstation.workstation_id, len(workstation.picking_buffer))

    # ── Schedule next stop or pod return ─────────────────────────────────────
    if len(task.stops) == 0:
        pod = sim.warehouse_status.get_pod(task.pod_id)
        return_travel_time = sim.warehouse_status.travel_time(
            sim.warehouse_status.cell2coord(workstation.position),
            sim.warehouse_status.cell2coord(pod.storage_location), 
            sim.RANDOM_GENERATOR
        )
        sim.future_events.push(Event(
            time=sim.current_time + return_travel_time,
            type=EventType.RETURN_POD,
            info=task
        ))
        logging.debug("Task %i completed: pod %i returning at its storage location.",
                     task.task_id, task.pod_id)
    else:
        next_visit = task.stops[0]
        next_workstation = sim.warehouse_status.get_workstation(next_visit.workstation_id)
        travel_time = sim.warehouse_status.travel_time(
            sim.warehouse_status.cell2coord(workstation.position), 
            sim.warehouse_status.cell2coord(next_workstation.position), 
            sim.RANDOM_GENERATOR
        )
        sim.future_events.push(Event(
            time=sim.current_time + travel_time,
            type=EventType.ARRIVAL_POD_WST,
            info=task
        ))
        logging.debug("Task %i heading towards next visit: robot %i heading to workstation %i.",
                     task.task_id, task.robot_id, next_visit.workstation_id)

    # ── Update order states ───────────────────────────────────────────────────
    completed_orders = []
    for order_id in completed_visit.orders:
        order = sim.orders_in_system.get(order_id)
        if order is None:
            continue
        order.items_pending -= completed_visit.items
        assert len(order.items_pending) >= 0, (
            f"Order {order_id} has negative pending items after picking"
        )
        if len(order.items_pending) == 0:
            completed_orders.append(order_id)
            sim.future_events.push(Event(
                time=sim.current_time,
                type=EventType.CLOSE_ORDER,
                info=order
            ))

    # Skip redesign if any order closed: close_order will handle it
    if completed_orders:
        return

    if not sim.optimization_enabled:
        new_tasks, sim.task_counter = design_tasks_for_ws(
            workstation=workstation,
            warehouse=sim.warehouse_status,
            orders_in_system=sim.orders_in_system,
            task_counter=sim.task_counter,
            active_tasks=sim.active_tasks
        )
        if new_tasks:
            for new_task in new_tasks:
                sim.future_events.push(Event(
                    time=sim.current_time,
                    type=EventType.RELEASE_TASK,
                    info=new_task
                ))
            logging.debug("Redesigning %i task(s) for workstation %i",
                         len(new_tasks), workstation.workstation_id)


def return_pod(event: Event, sim) -> None:
    """
    Return a pod to its storage location after task completion.

    Releases the robot and pod, marking them as IDLE. Triggers execution
    of the next available task if any exist.
    """
    task = event.info
    pod = sim.warehouse_status.get_pod(task.pod_id)
    robot = sim.warehouse_status.get_robot(task.robot_id)

    assert len(task.stops) == 0, (
        f"Task {task.task_id} has remaining stops at return: "
        f"{[v.workstation_id for v in task.stops]}"
    )
    assert pod.status == PodStatus.BUSY, (
        f"Pod {task.pod_id} should be BUSY at return, got {pod.status.name}"
    )
    assert robot.status == RobotStatus.BUSY, (
        f"Robot {task.robot_id} should be BUSY at return, got {robot.status.name}"
    )

    robot.status = RobotStatus.IDLE
    robot.position = pod.storage_location
    pod.status = PodStatus.IDLE
    sim.active_tasks.pop(task.task_id)

    sim.STAT_MANAGER.update_statistic(type='RB_FREQ', info=[robot.robot_id, RobotStatus.IDLE, sim.current_time])

    idle_robots = sum(1 for r in sim.warehouse_status.robots if r.status == RobotStatus.IDLE)
    logging.debug("Pod %i returned to its storage location. Robot %i is idle again.   "
                 "[idle_robots = %i/%i, released_tasks = %i]",
                 pod.pod_id, robot.robot_id, idle_robots,
                 len(sim.warehouse_status.robots), len(sim.released_tasks))

    if not sim.released_tasks.is_empty():
        sim.future_events.push(Event(time=sim.current_time, type=EventType.START_TASK))


def close_order(event: Event, sim) -> None:
    """
    Close a completed order and attempt to open the next queued order.

    Transitions order to CLOSED status and removes it from the workstation.
    If there are pending orders in the workstation queue, opens the first one.
    """
    order = event.info

    assert len(order.items_pending) == 0, (
        f"Cannot close order {order.order_id}: {len(order.items_pending)} items still pending"
    )
    assert order.status == OrderStatus.OPEN, (
        f"Order {order.order_id} expected OPEN at close, got {order.status.name}"
    )

    workstation = sim.warehouse_status.get_workstation(order.workstation_id)
    order.status = OrderStatus.CLOSED
    workstation.opened_orders.discard(order.order_id)

    sim.STAT_MANAGER.update_statistic(
        type='WS_AVG_OO',
        info=[workstation.workstation_id, len(workstation.opened_orders), sim.current_time]
    )
    sim.STAT_MANAGER.update_statistic(type='OFT', info=[order, sim.current_time])

    flow_time = sim.current_time - order.arrival_time
    logging.debug("Order %i closed at workstation %i: flow_time = %f.     "
                 "[order_buffer len = %i] [open_orders = %i / %i]",
                 order.order_id, workstation.workstation_id, flow_time,
                 len(workstation.order_buffer), len(workstation.opened_orders),
                 workstation.order_capacity)

    if workstation.order_buffer:
        next_order_id = workstation.order_buffer.pop(0)
        next_order = sim.orders_in_system.get(next_order_id)
        if next_order is not None:
            sim.future_events.push(Event(
                time=sim.current_time,
                type=EventType.OPEN_ORDER,
                info=next_order
            ))
            logging.debug("Next order in buffer has id %i", next_order_id)


def run_optimizer(event: Event, sim) -> None:
    """Execute the optimization routine (placeholder)."""
    
    # Solving the optimization model
    # This function will NOT CHANGE THE STATE of any entities but has access to it
    solve_exact_opt_model(sim)



#  Utility 

def _count_closed(sim) -> int:
    """Count closed orders. O(n) — consider maintaining a dedicated counter on sim."""
    return sum(1 for o in sim.orders_in_system if o.status == OrderStatus.CLOSED)