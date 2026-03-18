from dataclasses import dataclass, field
from enums import OrderStatus, RobotStatus, PodStatus, WorkstationPickingStatus

### MISSIONS-related classes

@dataclass
class Visit:
    """
    A single stop within a task.
    The pod must travel to this workstation and pick the listed SKUs
    for the specified order.
    """
    workstation_id: int
    order_id:       int
    sku_list:       list[int]  # SKUs to pick at this stop
    t_desired:      float      # time at which the optimizer wants the pod to arrive


@dataclass
class Task:
    """
    A complete mission released by the optimizer.
    Describes the full route of one pod through an ordered sequence of stops.
    """
    task_id:  int
    pod_id:   int
    visits:   list[Visit]  # ordered list of stops
    priority: float        # earliest release time = min(t_desired - travel_time) over visits




### OUTER SIMULATOR STATE
# Lives for the entire simulation run.
# Updated by both the optimizer and the emulator.

@dataclass
class OrderState:
    """
    All information the outer simulator tracks about a single order.
    """
    order_id:     int
    sku_required: list[int]             # SKUs needed to complete the order
    status:       OrderStatus = OrderStatus.BACKLOG
    assigned_ws:  int | None  # workstation assigned by the optimizer


@dataclass
class SimulatorState:
    """
    Global state of the outer simulator.
     — backlog          : orders that have arrived but not yet been optimized
     — orders           : orders already considered by the optimizer
     — robot positions  : last known position of every robot (grid cell)
     — missions         : task queue produced by the optimizer, consumed by the emulator
    """

    backlog: list[OrderState] = field(default_factory=list)
    orders: dict[int, OrderState] = field(default_factory=dict)
    robot_positions: dict[int, tuple[int, int]] = field(default_factory=dict)
    mission_queue: list[Task] = field(default_factory=list)



### EMULATOR STATE
# Re-initialised at every optimizer call.
# Tracks fine-grained movement and picking state.

@dataclass
class RobotState:
    """Fine-grained state of a single robot inside the emulator."""
    robot_id:        int
    status:          RobotStatus = RobotStatus.IDLE
    position:        tuple[int, int] = (0, 0)   # current grid cell
    current_task_id: int | None        # task being executed, if BUSY


@dataclass
class PodState:
    """Fine-grained state of a single pod inside the emulator."""
    pod_id:        int
    status:        PodStatus = PodStatus.IDLE
    home_position: tuple[int, int] = (0, 0)     # resting cell in the grid
    sku_ids:       list[int] = field(default_factory=list)  # SKUs stored on this pod


@dataclass
class WorkstationState:
    """
    Fine-grained state of a single workstation inside the emulator.

    open_orders      — order_ids currently being served (up to M at once)
    picking_status   — whether a picking action is in progress
    pod_queue        — pods that have arrived and are waiting (excluding the one
                       currently being picked); unordered list, matched by order_id
    order_queue      — sequence of order_ids to open next (set by the optimizer)
    pending_missions — missions that could not be released because pod_queue was full
    """
    workstation_id:   int
    capacity:         int   # M: max simultaneous open orders
    queue_capacity:   int   # max pods waiting in pod_queue

    open_orders:      list[int] = field(default_factory=list)
    picking_status:   WorkstationPickingStatus = WorkstationPickingStatus.IDLE
    pod_queue:        list[int] = field(default_factory=list)   # pod_ids waiting
    order_queue:      list[int] = field(default_factory=list)   # order_ids to open
    pending_missions: list[Task] = field(default_factory=list)


    # Helpful methods 
    def has_open_slot(self) -> bool:
        """True if at least one order slot is free."""
        return len(self.open_orders) < self.capacity

    def pod_queue_full(self) -> bool:
        """True if pod_queue has reached its capacity limit."""
        return len(self.pod_queue) >= self.queue_capacity

    def find_pod_for_order(self, order_id, active_tasks):
        """
        Scan pod_queue for the pod that is supposed to serve order_id at this workstation.

        active_tasks: mapping pod_id -> Task for all currently active tasks.
        Returns the pod_id if found, None otherwise.
        """
        for pod_id in self.pod_queue:
            task = active_tasks.get(pod_id)
            if task is None:
                continue
            for visit in task.visits:
                if visit.workstation_id == self.workstation_id and visit.order_id == order_id:
                    return pod_id
        return None


@dataclass
class EmulatorState:
    """
    Full state of the pod-movement emulator.

    robots       — fine-grained state of every robot         key: robot_id
    pods         — fine-grained state of every pod           key: pod_id
    workstations — fine-grained state of every workstation   key: workstation_id
    released_tasks — min-heap of tasks ready to be assigned to a robot
                     elements: (priority, tie_breaker, Task)
    active_tasks   — fast lookup for tasks currently in execution
                     key: pod_id  (one active task per pod at most)
    """
    robots:        dict[int, RobotState] = field(default_factory=dict)
    pods:          dict[int, PodState] = field(default_factory=dict)
    workstations:  dict[int, WorkstationState] = field(default_factory=dict)

    # min-heap: (priority, tie_breaker, Task)
    released_tasks: list = field(default_factory=list)

    # key: pod_id
    active_tasks: dict[int, Task] = field(default_factory=dict)
