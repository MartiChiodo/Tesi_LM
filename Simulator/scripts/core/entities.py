from typing import Any
from dataclasses import dataclass, field
from Simulator.scripts.core.enums import OrderStatus, RobotStatus, PodStatus, WorkstationPickingStatus, EventType


### MISSIONS-RELATED CLASSES

@dataclass
class Visit:
    """
    Represents a single stop within a task.

    A pod must travel to a specific workstation and pick a set of SKUs
    associated with a given order.

    Parameters:
    workstation_id : int     Identifier of the destination workstation.
    order_ids : list[int]       Orders being served at this stop.
    sku_list : list[int]     List of SKUs to be picked at this stop.
    """
    workstation_id: int
    order_ids : list[int]
    sku_list: list[int]


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
    priority : float      Priority parameter
    """
    task_id: int
    pod_id: int
    visits: list[Visit]

    priority : float



### OUTER SIMULATOR RELATED CLASSES
# Persistent across the entire simulation.
# Updated by both optimizer and emulator.

@dataclass
class Order:
    """
    Represents a customer order tracked by the outer simulator.

    Parameters
    ----------
    order_id : int              Unique identifier of the order.
    num_skus: int               Number of skus required by the order.
    sku_required : list[int]    List of SKUs required to complete the order.
    assigned_ws : int | None    Workstation assigned by the optimizer (None if not yet assigned).
    status : OrderStatus        Current lifecycle status of the order.
    """
    order_id: int
    arrival_time : float
    num_skus: int
    sku_required: list[int]
    sku_remaining: list[int]
    assigned_ws: int | None
    status: OrderStatus = OrderStatus.BACKLOG






### EMULATOR RELATED CLASSES
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

    open_orders : set(int)                     Orders currently being processed.
    pod_queue : list[int]                      Pods waiting at the workstation (excluding the active one).
    order_queue : list[int]                    Orders scheduled to be opened next.
    released_tasks : list[Visit]               Tasks already released but not allocated yet.
    active_tasks : list[Visit]                 Tasks already allocated.
    picking_status : WorkstationPickingStatus  Current picking activity state.
    """
    workstation_id: int
    openorder_capacity: int
    podqueue_capacity: int
    position: tuple[int, int]

    open_orders: set[int] = field(default_factory=set)
    pod_queue: list[int] = field(default_factory=list)
    order_queue: list[int] = field(default_factory=list)

    released_tasks: list[Visit] = field(default_factory=list)
    active_tasks : list[Visit] = field(default_factory=list)
    picking_status: WorkstationPickingStatus = WorkstationPickingStatus.IDLE


    # Utility methods

    def has_open_slot(self) -> bool:
        """
        Check whether the workstation can accept a new order.
        """
        return len(self.open_orders) < self.openorder_capacity

    def pod_queue_full(self) -> bool:
        """
        Check whether the pod waiting queue is full.
        """
        return len(self.pod_queue) + len(self.active_tasks) >= self.podqueue_capacity

    def find_pod_for_order(self, order_id: int, active_tasks: dict[int, Task]) -> int | None:
        """
        Find the pod assigned to serve a specific order at this workstation.
        """
        for pod_id in self.pod_queue:
            task = active_tasks.get(pod_id)
            if task is None:
                continue
            for visit in task.visits:
                if (
                    visit.workstation_id == self.workstation_id
                    and order_id in visit.order_ids   
                ):
                    return pod_id
        return None


### EVENT container

@dataclass
class Event:
    """
    Discrete-event simulation (DES) event.

    Parameters
    ----------
    time : float       Simulation time.
    type : EventType   Event type.
    info : Any         Optional payload.
    """
    time: float
    type: EventType
    info: Any = None  