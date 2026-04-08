import logging

from Simulator.scripts.core.entities import Order, Event
from Simulator.scripts.core.enums import OrderStatus, RobotStatus, PodStatus, WorkstationPickingStatus, EventType
from Simulator.scripts.opt.policies import *
from Simulator.scripts.sim.utils import *


def arrival_order(event, sim):
    """
    Handle a new order arrival.

    Generates an order following Barnhart et al. 2024:
    single-item with probability p, otherwise geometric(p) + 2 items.
    Adds the order to arrived_orders and schedules the next arrival.

    If optimization is disabled, immediately assigns the order to the
    least-loaded workstation: opens it directly if a slot is free,
    otherwise appends it to the workstation's order_queue.

    event.info : None   No payload expected.
    """

    order_id = len(sim.orders_in_system)

    ### Order generation (as in Barnhart2024)
    r = sim.RNG.random()
    ns = 1 if r < sim.order_gen_config[1] else sim.RNG.geometric(p=sim.order_gen_config[2]) + 2
    list_s = [sample_sku(sim.RNG, sim.warehouse_status.num_skus) for _ in range(ns)]

    ### Adding order to backlog
    o = Order(
        order_id=order_id,
        order_size=ns,
        items_required=set(list_s),
        items_pending=set(list_s.copy()),
        workstation_id=None,
        arrival_time=sim.current_time
    )
    sim.orders_in_system.push(o)

    ### Scheduling next order arrival
    e = Event(time=sim.current_time + sim.order_gen_config[0], type=EventType.ARRIVAL_ORDER)
    sim.future_events.push(e)

    ### Assigning order to ws if not using optimizer
    if not sim.optimization_enabled:
        id_ws = assign_order_to_workstation_policy(o, sim.warehouse_status.workstations)
        ws = sim.warehouse_status.workstations[id_ws]
        o.status, o.workstation_id = OrderStatus.WAITING, id_ws


        if ws.has_open_slot():
            sim.future_events.push(Event(time=sim.current_time, type=EventType.OPEN_ORDER, info = o))
        else:
            sim.warehouse_status.workstations[id_ws].order_buffer.append(order_id)
            logging.info('Order %i waiting at workstation %i', order_id, id_ws)

        
def open_order(event, sim):
    """
    Open an order at its assigned workstation.

    Sets the order status to OPEN and registers it in the
    workstation's open_orders set.

    event.info : Order   The order to open.
    """
    o = event.info
    ws = sim.warehouse_status.workstations[o.workstation_id]
    o.status = OrderStatus.OPEN
    ws.opened_orders.add(o.order_id)
    logging.info('Order %i opened at workstation %i', o.order_id, o.workstation_id)

    if not sim.optimization_enabled:
        tasks = design_tasks_for_ws(
            workstation=ws,
            warehouse=sim.warehouse_status,
            arrived_orders=sim.orders_in_system,
            task_counter=sim.task_counter
        )
        sim.task_counter += len(tasks)
        for t in tasks:
            sim.future_events.push(Event(time=sim.current_time, type=EventType.RELEASE_TASK, info=t))   
    else:
        for _ in range(ws.podqueue_capacity - (len(ws.pending_tasks) + len(ws.active_tasks))):
            sim.future_events.push(Event(time=sim.current_time, type=EventType.RELEASE_TASK, info=ws.workstation_id))  


def release_task(event, sim):
    """
    Push a task into released_tasks, making it available for execution.
    No physical state is modified — pod and robot remain unchanged until START_TASK.

    If optimization is enabled, pops the next task for the requesting workstation
    from scheduled_tasks (if capacity allows). If optimization is disabled, takes
    the task directly from event.info.

    Triggers START_TASK immediately if an idle robot is available.

    event.info : Task | int   Task to release (no optimizer) or workstation_id (optimizer).
    """

    ws_id = event.info if sim.optimization_enabled else event.info.stops[0].workstation_id
    ws = sim.warehouse_status.workstations[ws_id]

    if sim.optimization_enabled:
        if ws.pod_queue_full():
            logging.info('WS %i | Pod queue full, task not released', ws_id)
            return
        if sim.scheduled_tasks[ws_id].is_empty():
            logging.info('WS %i | No scheduled tasks available', ws_id)
            return
        task = sim.scheduled_tasks[ws_id].pop()
    else:
        task = event.info

    # Push to released queue
    sim.released_tasks.push(task)

    # Update released_tasks list of each involved workstation
    for v in task.stops:
        sim.warehouse_status.workstations[v.workstation_id].pending_tasks.append(task)

    logging.info('Task %i released — pod %i → workstation %i', task.task_id, task.pod_id, ws_id)

    # Trigger START_TASK if a robot is already idle
    if any(r.status == RobotStatus.IDLE for r in sim.warehouse_status.robots):
        sim.future_events.push(Event(time=sim.current_time, type=EventType.START_TASK))


def start_task(event, sim):
    """
    Assign the highest-priority released task to the nearest idle robot.

    Updates pod and robot status to BUSY, registers visits as active
    at their respective workstations, and schedules ARRIVAL_POD_WST
    for the first visit.

    event.info : None   No payload expected.
    """

    t = sim.released_tasks.pop()
    robot_id = get_nearest_idle_robot(sim.warehouse_status.pods[t.pod_id], sim.warehouse_status)

    if robot_id is None or not sim.warehouse_status.pods[t.pod_id].status == PodStatus.IDLE:
        logging.info('No task started.')
        return

    # Update robot and pod state
    pod = sim.warehouse_status.pods[t.pod_id]
    robot = sim.warehouse_status.robots[robot_id]
    pod.status = PodStatus.BUSY
    robot.status = RobotStatus.BUSY
    t.robot_id = robot.robot_id

    # Update workstation visit queues
    for v in t.stops:
        ws = sim.warehouse_status.workstations[v.workstation_id]
        if v in ws.pending_tasks:
            ws.pending_tasks.remove(v)
        ws.active_tasks.append(v)

    # Schedule arrival at first workstation
    first_visit = t.stops[0]
    ws_position = sim.warehouse_status.workstations[first_visit.workstation_id].position
    travel = sim.warehouse_status.travel_time(pod.storage_location, ws_position, sim.RNG)

    sim.future_events.push(Event(
        time=sim.current_time + travel,
        type=EventType.ARRIVAL_POD_WST,
        info=t
    ))

    logging.info(
    'Task %i started — pod %i picked up by robot %i, heading to workstation %i',
    t.task_id, t.pod_id, robot_id, first_visit.workstation_id
    )
    

def arrival_pod_wst(event, sim):
    
    # Retrieveng visit and updating robot position
    current_v = event.info.stops[0]
    sim.warehouse_status.robots[event.info.robot_id].position = sim.warehouse_status.workstations[current_v.workstation_id].position

    # Checking if the workstation is idle or not
    ws = sim.warehouse_status.workstations[current_v.workstation_id]
    if ws.status == WorkstationPickingStatus.IDLE:
        # Scheduling picking event
        sim.future_events.push(Event(
            time=sim.current_time,
            type=EventType.START_PICKING,
            info=(event.info)
        ))
    else:
        # Enqueuing the pod at the buffer
        ws.pod_buffer.append(event.info.task_id)
        logging.info(
            'Task %i: Robot %i (moving pod %i) enqueued at workstation %i',
            event.info[0].task_id, event.info[1], event.info[0].pod_id, current_v.workstation_id
            )



def start_picking(event, sim):
    
    # Retrieveng visit
    v = event.info.stops[0]

    # updating ws status
    sim.warehouse_status.workstations[v.workstation_id].status = WorkstationPickingStatus.BUSY

    # Scheduling end event
    estimated_picking_time =  sim.warehouse_status.workstations[v.workstation_id].estimated_picking_time(len(v.items))
    sim.future_events.push(Event(
            time=sim.current_time + estimated_picking_time,
            type=EventType.END_PICKING,
            info=(event.info)
        ))
    
    logging.info(
            'Task %i: Picking at workstation %i - items %s are picked for orders %s',
            event.info.task_id, v.workstation_id, v.items, v.orders, 
            )


def end_picking(event, sim):
    
    # Chnging ws status
    v = event.info.stops[0]
    sim.warehouse_status.workstations[v.workstation_id].status = WorkstationPickingStatus.IDLE

    # Popping ended visit
    event.info.stops.pop(0)

    # Updating order info and checking if I can close an order
    for id_o in v.orders:
        o = sim.orders_in_system.get(id_o)
        o.items_pending -= v.items

        if len(o.items_pending) ==  0:
            sim.future_events.push(Event(
                time=sim.current_time,
                type=EventType.CLOSE_ORDER,
                info=(o, v.workstation_id)
                ))
            

    # Checking if I can schedule another picking operation
    if len(sim.warehouse_status.workstations[v.workstation_id].task_buffer) > 0:
        task_id = sim.warehouse_status.workstations[v.workstation_id].task_buffer[0]
        sim.warehouse_status.workstations[v.workstation_id].task_buffer.pop(0)
        task =  sim.released_task.get(task_id)

        sim.future_events.push(Event(
            time=sim.current_time,
            type=EventType.START_PICKING,
            info=(task)
        ))

    # Checking if the task need another stop or the pode can go back home
    t = event.info
    if len(event.info.stops) == 0:
        ws_status = sim.warehouse_status
        travel_time = ws_status.travel_time(ws_status.pods[t.pod_id].storage_location, ws_status.robots[t.robot_id].position, sim.RNG)
        sim.future_events.push(Event(
            time=sim.current_time + travel_time,
            type=EventType.RETURN_POD,
            info=(t)
        ))
        logging.info(
            'Task %i — pod %i and robot %i, heading to pod storage location',
            t.task_id, t.pod_id, t.robot_id
            )

    else:
        next_vis = t.stops[0]
        travel_time = ws_status.travel_time(ws_status.workstations[next_vis.workstation_id].position, ws_status.robots[t.robot_id].position, sim.RNG)
        sim.future_events.push(Event(
            time=sim.current_time + travel_time,
            type=EventType.ARRIVAL_POD_WST,
            info=(t)
        ))
        logging.info(
            'Task %i — pod %i still with robot %i, heading to workstation %i',
            t.task_id, t.pod_id, t.robot_id, next_vis.workstation_id
            )


def return_pod(event, sim):
    
    # Updating pod and robot status
    t = event.info
    sim.warehouse_status.robots[t.robot_id].status = RobotStatus.IDLE
    sim.warehouse_status.robots[t.robot_id].position = sim.warehouse_status.pods[t.pod_id].storage_location
    sim.warehouse_status.pods[t.pod_id].status = PodStatus.IDLE

    # Starting new task if available
    if len(sim.released_tasks) > 0:
        sim.future_events.push(Event(
                time=sim.current_time,
                type=EventType.START_TASK,
                info=None
                ))


def close_order(event, sim):
    pass


def run_optimizer(event, sim):
    pass