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


def arrival_order(event: Event, sim) -> None:
    """
    Handle a new customer order arrival.

    Generates an order following Barnhart et al. 2024: single-item with 
    probability p, otherwise geometric(p) + 2 items. Adds the order to 
    the system backlog and schedules the next order arrival.

    If optimization is disabled, immediately assigns the order to the 
    least-loaded workstation and opens it if a slot is available.
    """
    
    # Generate order ID and size
    order_id = sim.orders_counter
    sim.orders_counter += 1
    
    # Sample order size: 1 item with prob p, else geometric distribution
    rnd = sim.RANDOM_GENERATOR.random()
    if rnd < sim.order_gen_config[1]:
        order_size = 1
    else:
        order_size = sim.RANDOM_GENERATOR.geometric(p=sim.order_gen_config[2]) + 2
    
    # Generate SKU list
    sku_list = [
        sample_sku(sim.RANDOM_GENERATOR, sim.warehouse_status.num_skus) 
        for _ in range(order_size)
    ]
    
    # Create order and add to backlog
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
    
    logging.info(
        "[t=%.2f] Order arrived | order_id=%d, size=%d, num_skus=%d",
        sim.current_time, order_id, order_size, len(set(sku_list))
    )
    
    # Schedule next order arrival
    interarrival_time = sim.order_gen_config[0]
    next_arrival_event = Event(
        time=sim.current_time + interarrival_time,
        type=EventType.ARRIVAL_ORDER
    )
    sim.future_events.push(next_arrival_event)
    
    # Assign to workstation if not using optimization
    if not sim.optimization_enabled:
        workstation_id = assign_order_to_workstation_policy(
            o, 
            sim.warehouse_status.workstations
        )
        workstation = sim.warehouse_status.get_workstation(workstation_id)
        o.workstation_id = workstation_id
        o.status = OrderStatus.WAITING
        
        if workstation.has_open_slot():
            # Open order immediately
            open_event = Event(
                time=sim.current_time,
                type=EventType.OPEN_ORDER,
                info=o
            )
            sim.future_events.push(open_event)
        else:
            # Queue for later opening
            workstation.order_buffer.append(order_id)
            logging.info(
                "[t=%.2f] Order queued (no capacity) | order_id=%d, ws_id=%d, queue_len=%d",
                sim.current_time, order_id, workstation_id, len(workstation.order_buffer)
            )


def open_order(event: Event, sim) -> None:
    """
    Open an order at its assigned workstation.

    Transitions the order from WAITING to OPEN status and registers it
    in the workstation's active orders. If optimization is disabled, 
    immediately designs tasks to fetch pods matching the order SKUs.
    """
    
    o = event.info
    
    # Validate precondition
    if o.workstation_id is None:
        raise ValueError(
            f"Cannot open order {o.order_id}: no workstation assigned"
        )
    
    workstation = sim.warehouse_status.get_workstation(o.workstation_id)
    
    # Verify state transition
    assert o.status == OrderStatus.WAITING, (
        f"Order {o.order_id} state transition error: "
        f"expected WAITING, got {o.status.name}"
    )
    
    # Update order state
    o.status = OrderStatus.OPEN
    workstation.opened_orders.add(o.order_id)
    
    logging.info(
        "[t=%.2f] Order opened | order_id=%d, ws_id=%d, items_pending=%d",
        sim.current_time, o.order_id, o.workstation_id, len(o.items_pending)
    )
    
    # Design tasks if not using optimization
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
            
            logging.info(
                "[t=%.2f] Tasks designed | ws_id=%d, num_tasks=%d, total_items=%d",
                sim.current_time, o.workstation_id, len(tasks), total_items
            )
            
            # Schedule task releases
            for t in tasks:
                release_event = Event(
                    time=sim.current_time,
                    type=EventType.RELEASE_TASK,
                    info=t
                )
                sim.future_events.push(release_event)
        else:
            logging.info(
                "[t=%.2f] No tasks designed | ws_id=%d, order_id=%d",
                sim.current_time, o.workstation_id, o.order_id
            )
    else:
        # Optimization path: request tasks from optimizer
        available_capacity = workstation.released_task_capacity - workstation.counter_released_task
        for _ in range(available_capacity):
            request_event = Event(
                time=sim.current_time,
                type=EventType.RELEASE_TASK,
                info=o.workstation_id
            )
            sim.future_events.push(request_event)


def release_task(event: Event, sim) -> None:
    """
    Release a task to the execution queue.

    Moves a task from scheduled_tasks or event payload to released_tasks,
    making it eligible for execution by an idle robot. Immediately triggers
    START_TASK if an idle robot is available.
    """
    
    if sim.optimization_enabled:
        workstation_id = event.info
    else:
        task = event.info
        workstation_id = task.stops[0].workstation_id
    
    workstation = sim.warehouse_status.get_workstation(workstation_id)
    
    # Retrieve task based on optimization mode
    if sim.optimization_enabled:
        if not workstation.can_release_task():
            return
        
        if sim.scheduled_tasks[workstation_id].is_empty():
            return
        
        task = sim.scheduled_tasks[workstation_id].pop()
    else:
        task = event.info
    
    # Add to released queue
    try:
        sim.released_tasks.update(task)
    except ValueError:
        sim.released_tasks.push(task)
    
    # Register as pending at all involved workstations
    for visit in task.stops:
        workstation = sim.warehouse_status.get_workstation(visit.workstation_id)
        workstation.released_tasks.add(task.task_id) 
    
    logging.info(
        "[t=%.2f] Task released | task_id=%d, pod_id=%d, ws_id=%d",
        sim.current_time, task.task_id, task.pod_id, workstation_id
    )
    
    # Trigger execution if idle robot available
    has_idle_robot = any(
        robot.status == RobotStatus.IDLE 
        for robot in sim.warehouse_status.robots
    )
    if has_idle_robot:
        start_event = Event(time=sim.current_time, type=EventType.START_TASK)
        sim.future_events.push(start_event)


def start_task(event: Event, sim) -> None:
    """
    Start executing a task with the nearest idle robot.

    Assigns the highest-priority released task to the nearest idle robot.
    Updates pod and robot status to BUSY, registers visits as active,
    and schedules pod arrival at the first workstation.
    """

    assert not sim.released_tasks.is_empty(), "START_TASK called but no released tasks to start."
    
    task = sim.released_tasks.peek()
    pod = sim.warehouse_status.get_pod(task.pod_id)
    
    # Check preconditions
    if pod.status != PodStatus.IDLE:
        logging.info(
            "[t=%.2f] Task cannot start | pod_id=%d, pod_status=%s (expected IDLE)",
            sim.current_time, task.pod_id, pod.status.name
        )
        return
    
    robot_id = get_nearest_idle_robot(pod, sim.warehouse_status)
    if robot_id is None:
        logging.info(
            "[t=%.2f] No idle robots available | task_id=%d deferred",
            sim.current_time, task.task_id
        )
        return
    
    # Remove task from released queue and update state
    task = sim.released_tasks.pop()
    sim.active_tasks[task.task_id] = task
    robot = sim.warehouse_status.get_robot(robot_id)
    
    pod.status = PodStatus.BUSY
    robot.status = RobotStatus.BUSY
    task.robot_id = robot_id
    
    # Move visits from pending to active at all workstations
    for visit in task.stops:
        workstation = sim.warehouse_status.get_workstation(visit.workstation_id)
        workstation.active_tasks.add(task.task_id)
        workstation.released_tasks.remove(task.task_id)
    
    # Schedule arrival at first workstation
    first_visit = task.stops[0]
    first_workstation = sim.warehouse_status.get_workstation(first_visit.workstation_id)
    travel_time = sim.warehouse_status.travel_time(
        pod.storage_location,
        first_workstation.position,
        sim.RANDOM_GENERATOR
    )
    
    arrival_event = Event(
        time=sim.current_time + travel_time,
        type=EventType.ARRIVAL_POD_WST,
        info=task
    )
    sim.future_events.push(arrival_event)
    
    logging.info(
        "[t=%.2f] Task started | task_id=%d, pod_id=%d, robot_id=%d, "
        "arrival_ws=%d, travel_time=%.2f",
        sim.current_time, task.task_id, task.pod_id, robot_id,
        first_visit.workstation_id, travel_time
    )


def arrival_pod_wst(event: Event, sim) -> None:
    """
    Handle pod arrival at a workstation.

    Updates robot position and checks if the workstation is idle.
    If idle, immediately starts picking; otherwise, queues the pod.
    """
    
    task = event.info
    current_visit = task.stops[0]
    
    # Update robot position
    workstation = sim.warehouse_status.get_workstation(current_visit.workstation_id)
    robot = sim.warehouse_status.get_robot(task.robot_id)
    robot.position = workstation.position
    
    logging.info(
        "[t=%.2f] Pod arrived at workstation | task_id=%d, pod_id=%d, robot_id=%d, ws_id=%d",
        sim.current_time, task.task_id, task.pod_id, task.robot_id, workstation.workstation_id
    )
    
    # Check workstation availability
    if workstation.status == WorkstationPickingStatus.IDLE:
        # Start picking immediately
        picking_event = Event(
            time=sim.current_time,
            type=EventType.START_PICKING,
            info=task
        )
        sim.future_events.push(picking_event)
    else:
        # Queue pod for later processing
        workstation.picking_buffer.append(task.task_id)
        logging.info(
            "[t=%.2f] Pod queued (ws busy) | task_id=%d, pod_id=%d, ws_id=%d, queue_len=%d",
            sim.current_time, task.task_id, task.pod_id, workstation.workstation_id,
            len(workstation.picking_buffer)
        )


def start_picking(event: Event, sim) -> None:
    """
    Start picking items from an arrived pod.

    Sets workstation status to BUSY and schedules picking completion
    based on pod process time and number of items.
    """
    
    task = event.info
    visit = task.stops[0]
    workstation = sim.warehouse_status.get_workstation(visit.workstation_id)
    
    # Update workstation state
    workstation.status = WorkstationPickingStatus.BUSY
    
    # Compute picking duration
    picking_time = workstation.estimated_picking_time(len(visit.items))
    
    logging.info(
        "[t=%.2f] Picking started | task_id=%d, pod_id=%d, ws_id=%d, "
        "num_items=%d, duration=%.2f",
        sim.current_time, task.task_id, task.pod_id, visit.workstation_id,
        len(visit.items), picking_time
    )
    
    # Schedule picking completion
    end_event = Event(
        time=sim.current_time + picking_time,
        type=EventType.END_PICKING,
        info=task
    )
    sim.future_events.push(end_event)


def end_picking(event: Event, sim) -> None:
    """
    Handle picking completion at a workstation.

    Updates order state, closes completed orders, removes the current
    visit from the task, and schedules either next workstation visit
    or pod return to storage.
    """
    
    task = event.info
    completed_visit = task.stops[0]
    workstation = sim.warehouse_status.get_workstation(completed_visit.workstation_id)
    
    # Update workstation status
    workstation.status = WorkstationPickingStatus.IDLE
    workstation.active_tasks.remove(task.task_id)
    
    logging.info(
        "[t=%.2f] Picking ended | task_id=%d, ws_id=%d, num_items=%d",
        sim.current_time, task.task_id, completed_visit.workstation_id, len(completed_visit.items)
    )
    
    # Remove completed visit from task
    task.stops.pop(0)
    
    # Update order states and close completed orders
    for order_id in completed_visit.orders:
        order = sim.orders_in_system.get(order_id)
        if order is not None:
            order.items_pending -= completed_visit.items
            
            if len(order.items_pending) == 0:
                close_event = Event(
                    time=sim.current_time,
                    type=EventType.CLOSE_ORDER,
                    info=order
                )
                sim.future_events.push(close_event)

    
    # Handle next stop or pod return
    if len(task.stops) == 0:
        # Pod has completed all stops - return to storage
        pod = sim.warehouse_status.get_pod(task.pod_id)
        robot = sim.warehouse_status.get_robot(task.robot_id)
        
        return_travel_time = sim.warehouse_status.travel_time(
            workstation.position,
            pod.storage_location,
            sim.RANDOM_GENERATOR
        )
        
        return_event = Event(
            time=sim.current_time + return_travel_time,
            type=EventType.RETURN_POD,
            info=task
        )
        sim.future_events.push(return_event)
        
        logging.info(
            "[t=%.2f] Task complete (all stops done) | task_id=%d, pod_id=%d, "
            "robot_id=%d, return_time=%.2f",
            sim.current_time, task.task_id, task.pod_id, task.robot_id, return_travel_time
        )
    else:
        # More stops remaining
        next_visit = task.stops[0]
        next_workstation = sim.warehouse_status.get_workstation(next_visit.workstation_id)
        robot = sim.warehouse_status.get_robot(task.robot_id)
        
        travel_time = sim.warehouse_status.travel_time(
            workstation.position,
            next_workstation.position,
            sim.RANDOM_GENERATOR
        )
        
        next_arrival_event = Event(
            time=sim.current_time + travel_time,
            type=EventType.ARRIVAL_POD_WST,
            info=task
        )
        sim.future_events.push(next_arrival_event)
        
        logging.info(
            "[t=%.2f] Task continuing | task_id=%d, next_ws=%d, travel_time=%.2f",
            sim.current_time, task.task_id, next_visit.workstation_id, travel_time
        )
    
    # Redesign tasks if optimization disabled
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
                release_event = Event(
                    time=sim.current_time,
                    type=EventType.RELEASE_TASK,
                    info=new_task
                )
                sim.future_events.push(release_event)
            
            logging.info(
                "[t=%.2f] New tasks designed after picking | ws_id=%d, num_tasks=%d",
                sim.current_time, workstation.workstation_id, len(new_tasks)
            )


    # Triggering start_picking
    if len(workstation.picking_buffer) > 0:
        task_id = workstation.picking_buffer.pop(0)
        task = sim.active_tasks[task_id]
        trigger_picking = Event(
                    time=sim.current_time,
                    type=EventType.START_PICKING,
                    info=task
                )
        sim.future_events.push(trigger_picking)


def return_pod(event: Event, sim) -> None:
    """
    Return a pod to its storage location after task completion.

    Releases the robot and pod, marking them as IDLE. Triggers execution
    of the next available task if any exist.
    """
    
    task = event.info
    pod = sim.warehouse_status.get_pod(task.pod_id)
    robot = sim.warehouse_status.get_robot(task.robot_id)
    
    # Validate postcondition
    assert len(task.stops) == 0, (
        f"Task {task.task_id} has remaining stops at return: "
        f"{[v.workstation_id for v in task.stops]}"
    )
    
    # Update state
    robot.status = RobotStatus.IDLE
    robot.position = pod.storage_location
    pod.status = PodStatus.IDLE
    sim.active_tasks.pop(task.task_id)
 
    logging.info(
        "[t=%.2f] Pod returned to storage | task_id=%d, pod_id=%d, robot_id=%d",
        sim.current_time, task.task_id, task.pod_id, task.robot_id
    )
    
    # Start next task if any available
    if not sim.released_tasks.is_empty():
        next_task_event = Event(
            time=sim.current_time,
            type=EventType.START_TASK
        )
        sim.future_events.push(next_task_event)


def close_order(event: Event, sim) -> None:
    """
    Close a completed order and attempt to open the next queued order.

    Transitions order to CLOSED status and removes it from the workstation.
    If there are pending orders in the workstation queue, opens the first one.
    """
    
    order = event.info
    
    # Validate postcondition
    assert len(order.items_pending) == 0, (
        f"Cannot close order {order.order_id}: has {len(order.items_pending)} "
        f"pending items remaining"
    )
    
    workstation = sim.warehouse_status.get_workstation(order.workstation_id)
    
    # Update order state
    order.status = OrderStatus.CLOSED
    
    
    logging.info(
        "[t=%.2f] Order closed | order_id=%d, ws_id=%d, total_items=%d",
        sim.current_time, order.order_id, order.workstation_id, order.order_size
    )
    
    workstation.opened_orders.remove(order.order_id)

    # Open next queued order if available
    if len(workstation.order_buffer) > 0:
        next_order_id = workstation.order_buffer.pop(0)
        next_order = sim.orders_in_system.get(next_order_id)
        
        if next_order is not None:
            open_event = Event(
                time=sim.current_time,
                type=EventType.OPEN_ORDER,
                info=next_order
            )
            sim.future_events.push(open_event)



def run_optimizer(event: Event, sim) -> None:
    """
    Execute the optimization routine.

    Placeholder for optimizer-based task scheduling. This function is
    called periodically (every DELTA_T_OPT minutes) when optimization
    is enabled.

    Parameters
    ----------
    event : Event
        Event (no payload required).
    sim : Simulator
        Simulator instance for state access and event scheduling.

    Notes
    -----
    To be implemented with actual optimization logic (e.g., MIP solver).
    """
    pass