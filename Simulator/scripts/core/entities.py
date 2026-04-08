from typing import Any
from dataclasses import dataclass, field
from Simulator.scripts.core.enums import OrderStatus, RobotStatus, PodStatus, WorkstationPickingStatus, EventType


### MISSIONS-RELATED CLASSES

@dataclass
class Visit:
    """
    Represents a single stop within a task.

    A pod must travel to a specific workstation and pick a set of items
    associated with a given order.

    Parameters
    ----------
    workstation_id : int    Identifier of the destination workstation.
    orders : list[int]      Orders being served at this stop.
    items : list[int]       Set of items (SKUs) to be picked at this stop.
    """
    workstation_id: int
    orders: set[int]
    items: set[int]


@dataclass
class Task:
    """
    Represents a full mission assigned to a pod-robot pair.

    A task consists of an ordered sequence of stops that define
    the route and picking operations for a pod.

    Parameters
    ----------
    task_id : int          Unique identifier of the task.
    pod_id : int           Identifier of the pod executing the task.
    robot_id : int | None  Identifier of the robot allocated to the task.
    stops : list[Visit]    Ordered list of stops to be executed, pop() is used during END_PICKING
    priority : float       Scheduling priority of the task.
    """
    task_id: int
    pod_id: int
    robot_id: int | None
    stops: list[Visit]
    priority: float



### OUTER SIMULATOR RELATED CLASSES
# Persistent across the entire simulation.
# Updated by both optimizer and emulator.

@dataclass
class Order:
    """
    Represents a customer order tracked by the outer simulator.

    Parameters
    ----------
    order_id : int               Unique identifier of the order.
    arrival_time : float         Simulation time at which the order arrived.
    order_size : int             Total number of items required by the order.
    items_required : list[int]   List of items (SKUs) required to complete the order.
    items_pending : list[int]    Items not yet picked (decremented during execution).
    workstation_id : int | None  Workstation assigned by the optimizer (None if not yet assigned).
    status : OrderStatus         Current lifecycle status of the order.
    """
    order_id: int
    arrival_time: float
    order_size: int
    items_required: set[int]
    items_pending: set[int]
    workstation_id: int | None
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
    status : RobotStatus          Current operational status of the robot.
    """
    robot_id: int
    position: tuple[int, int]
    status: RobotStatus = RobotStatus.IDLE


@dataclass
class Pod:
    """
    Represents the fine-grained state of a pod.

    Parameters
    ----------
    pod_id : int                         Unique identifier of the pod.
    storage_location : tuple[int, int]   Default grid cell where the pod rests when idle.
    items : list[int]                    Items (SKUs) currently stored in the pod.
    status : PodStatus                   Current operational status of the pod.
    """
    pod_id: int
    storage_location: tuple[int, int]
    items: set[int] = field(default_factory=list)
    status: PodStatus = PodStatus.IDLE


@dataclass
class Workstation:
    """
    Represents the fine-grained state of a workstation.

    Attributes
    ----------
    workstation_id : int          Unique identifier of the workstation.
    order_capacity : int          Maximum number of simultaneously active orders.
    workload_capacity : int       Maximum number of tasks simultanesosly released.
    position : tuple[int, int]    Grid position of the workstation.
     pod_process_time : float     Time to process a pod arrived to a picking station.
    item_process_time : float     Time to pick a single item to a picking station.

    opened_orders : set[int]                   Orders currently being processed.
    task_buffer : list[int]                    Pods waiting at the workstation (excluding the active one).
    order_buffer : list[int]                   Orders scheduled to be opened next.
    pending_tasks : list[Visit]                Tasks released but not yet allocated to a robot.
    active_tasks : list[Visit]                 Tasks currently allocated to a robot.
    status : WorkstationPickingStatus          Current picking activity state.
    """
    workstation_id: int
    order_capacity: int
    workload_capacity: int
    position: tuple[int, int]
    pod_process_time : float
    item_process_time : float

    opened_orders: set[int] = field(default_factory=set)
    task_buffer: list[int] = field(default_factory=list)
    order_buffer: list[int] = field(default_factory=list)

    pending_tasks: list[Visit] = field(default_factory=list)
    active_tasks: list[Visit] = field(default_factory=list)
    status: WorkstationPickingStatus = WorkstationPickingStatus.IDLE


    # Utility methods

    def has_open_slot(self) -> bool:
        """
        Check whether the workstation can accept a new order.
        """
        return len(self.opened_orders) < self.order_capacity

    def overloaded_workstation(self) -> bool:
        """
        Check whether the workstation has workload left.
        """
        return len(self.pod_buffer) + len(self.active_tasks) >= self.workload_capacity

    def find_pod_for_order(self, order_id: int, active_tasks: dict[int, Task]) -> int | None:
        """
        Find the pod assigned to serve a specific order at this workstation.
        """
        for pod_id in self.pod_buffer:
            task = active_tasks.get(pod_id)
            if task is None:
                continue
            for stop in task.stops:
                if (
                    stop.workstation_id == self.workstation_id
                    and order_id in stop.orders
                ):
                    return pod_id
        return None
    
    def estimated_picking_time(self, num_items) -> float:
        return self.pod_process_time + num_items*self.item_process_time


### EVENT container

@dataclass
class Event:
    """
    Discrete-event simulation (DES) event.

    Parameters
    ----------
    time : float       Simulation time at which the event is scheduled.
    type : EventType   Event type.
    info : Any         Optional payload carrying event-specific data.
    """
    time: float
    type: EventType
    info: Any = None