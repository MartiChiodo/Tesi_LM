from dataclasses import dataclass, field
from Simulator.scripts.core.enums import OrderStatus, RobotStatus, PodStatus, WorkstationPickingStatus



### MISSIONS-RELATED CLASSES

@dataclass
class Visit:
    """
    Represents a single stop within a task.

    A pod must travel to a specific workstation and pick a set of SKUs
    associated with a given order.

    Parameters:
    workstation_id : int     Identifier of the destination workstation.
    order_id : int           Identifier of the order being served.
    sku_list : list[int]     List of SKUs to be picked at this stop.
    t_desired : float        Target arrival time specified by the optimizer.
    """
    workstation_id: int
    order_id: int
    sku_list: list[int]
    t_desired: float


@dataclass
class Task:
    """
    Represents a full mission assigned to a pair pod-robot.

    A task consists of an ordered sequence of visits that define
    the route and picking operations for a pod.

    Parameters
    ----------
    task_id : int         Unique identifier of the task.
    pod_id : int          Identifier of the pod executing the task.
    visits : list[Visit]  Ordered list of stops to be executed.
    priority : float      Scheduling priority (lower values typically indicate earlier execution).
                          Usually computed as: min(t_desired - travel_time) across all visits.
    """
    task_id: int
    pod_id: int
    visits: list[Visit]
    priority: float



### OUTER SIMULATOR STATE
# Persistent across the entire simulation.
# Updated by both optimizer and emulator.

@dataclass
class Order:
    """
    Represents a customer order tracked by the outer simulator.

    Parameters
    ----------
    order_id : int              Unique identifier of the order.
    sku_required : list[int]    List of SKUs required to complete the order.
    assigned_ws : int | None    Workstation assigned by the optimizer (None if not yet assigned).
    status : OrderStatus        Current lifecycle status of the order.
    """
    order_id: int
    sku_required: list[int]
    assigned_ws: int | None
    status: OrderStatus = OrderStatus.BACKLOG


@dataclass
class SimulatorState:
    """
    Global state of the outer simulator.

    Attributes
    ----------
    backlog_orders :       Orders that have arrived but are not yet processed by the optimizer.
    processed_orders :     Orders already processed by the optimizer.
    robot_positions :      Last known positions of robots (robot_id -> (x, y)).
    mission_queue :        Queue of tasks produced by the optimizer and consumed by the emulator.
    """
    backlog_orders: list[Order]
    processed_orders: list[Order]
    robot_positions: dict[int, tuple[int, int]] = field(default_factory=dict)
    mission_queue: list[Task] = field(default_factory=list)




### EMULATOR STATE
# Re-initialized at every optimizer call.
# Tracks detailed execution state.

@dataclass
class Robot:
    """
    Represents the fine-grained state of a robot.

    Parameters
    ----------
    robot_id : int                Unique identifier of the robot.
    position : tuple[int, int]    Current grid position of the robot.
    current_task_id : int | None  ID of the task currently being executed (None if idle).
    status : RobotStatus          Current robot status.
    """
    robot_id: int
    position: tuple[int, int]
    current_task_id: int | None
    status: RobotStatus = RobotStatus.IDLE


@dataclass
class Pod:
    """
    Represents the fine-grained state of a pod.

    Parameters
    ----------
    pod_id : int                      Unique identifier of the pod.
    home_position : tuple[int, int]   Default storage location of the pod.
    sku_ids : list[int]               SKUs stored in the pod.
    status : PodStatus                Current pod status.
    """
    pod_id: int
    home_position: tuple[int, int]
    sku_ids: list[int] = field(default_factory=list)
    status: PodStatus = PodStatus.IDLE


@dataclass
class Workstation:
    """
    Represents the fine-grained state of a workstation.

    Attributes
    ----------
    workstation_id : int        Unique identifier of the workstation.
    openorder_capacity : int    Maximum number of simultaneously open orders.
    podqueue_capacity : int     Maximum number of pods allowed in the waiting queue.
    position : tuple[int, int]  Grid position of the workstation.

    open_orders : list[int]                    Orders currently being processed.
    pod_queue : list[int]                      Pods waiting at the workstation (excluding the active one).
    order_queue : list[int]                    Orders scheduled to be opened next.
    pending_missions : list[Task]              Tasks that could not be released due to capacity constraints.
    picking_status : WorkstationPickingStatus  Current picking activity state.
    """
    workstation_id: int
    openorder_capacity: int
    podqueue_capacity: int
    position: tuple[int, int]

    open_orders: list[int] = field(default_factory=list)
    pod_queue: list[int] = field(default_factory=list)
    order_queue: list[int] = field(default_factory=list)
    pending_missions: list[Task] = field(default_factory=list)
    picking_status: WorkstationPickingStatus = WorkstationPickingStatus.IDLE

    # --------------------------------------------------------
    # Utility methods
    # --------------------------------------------------------

    def has_open_slot(self) -> bool:
        """
        Check whether the workstation can accept a new order.

        Returns
        -------
        bool: True if at least one order slot is available.
        """
        return len(self.open_orders) < self.openorder_capacity

    def pod_queue_full(self) -> bool:
        """
        Check whether the pod waiting queue is full.

        Returns
        -------
        bool: True if the queue has reached its capacity.
        """
        return len(self.pod_queue) >= self.podqueue_capacity

    def find_pod_for_order(self, order_id: int, active_tasks: dict[int, Task]) -> int | None:
        """
        Find the pod assigned to serve a specific order at this workstation.

        Parameters
        ----------
        order_id : int                   Target order identifier.
        active_tasks : dict[int, Task]   Mapping from pod_id to currently active Task.

        Returns
        -------
        int | None: pod_id if a matching pod is found, None otherwise.
        """
        for pod_id in self.pod_queue:
            task = active_tasks.get(pod_id)
            if task is None:
                continue

            for visit in task.visits:
                if (
                    visit.workstation_id == self.workstation_id
                    and visit.order_id == order_id
                ):
                    return pod_id

        return None


@dataclass
class EmulatorState:
    """
    Full execution state of the emulator.

    Attributes
    ----------
    robots : list[Robot]              List of all robots.
    pods : list[Pod]                  List of all pods.
    workstations : list[Workstation]  List of all workstations.

    released_tasks : list[Task]       Min-heap of tasks ready for execution (priority queue).
    active_tasks : dict[int, Task]    Mapping from pod_id to currently active task.
    """
    robots: list[Robot]
    pods: list[Pod]
    workstations: list[Workstation]

    released_tasks: list[Task]
    active_tasks: dict[int, Task]