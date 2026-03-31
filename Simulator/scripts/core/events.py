import heapq
from dataclasses import dataclass
from typing import Any
from enum import Enum



### EVENTS

class EventType(Enum):
    """
    Enumeration of all event types used in the simulator.
    """

    # --- Outer simulator ---
    ARRIVAL_ORDER = "arrival_order"
    RUN_OPTIMIZER = "run_optimizer"

    # --- Emulator ---
    RELEASE_TASK = "release_task"
    START_TASK = "start_task"
    ARRIVAL_POD_WST = "arrival_pod_wst"
    OPEN_ORDER = "open_order"
    START_PICKING = "start_picking"
    END_PICKING = "end_picking"
    CLOSE_ORDER = "close_order"
    RETURN_POD = "return_pod"

    # Utilities
    def __str__(self) -> str:
        return self.value


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



### EVENT QUEUE

class EventQueue:
    """
    Priority queue for DES events ordered by simulation time.

    Uses a monotonic counter to break ties and avoid direct comparison
    between Event objects.
    """

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, Event]] = []
        self._counter: int = 0

    # Scheduling
    def schedule(self, time: float, type: EventType, info: Any = None) -> Event:
        """
        Schedule a new event.

        Parameters
        ----------
        time : float        Event execution time.
        type : EventType    Event type.
        info : Any          Optional payload.

        Returns
        -------
        Event  The created event instance.
        """
        if time < 0:
            raise ValueError("Event time must be non-negative")

        event = Event(time=time, type=type, info=info)
        heapq.heappush(self._heap, (time, self._counter, event))
        self._counter += 1
        return event

    # Retrieval
    def pop(self) -> Event:
        """
        Remove and return the earliest scheduled event.

        Returns
        -------
        Event  Earliest event in the queue.

        Raises
        ------
        IndexError  If the queue is empty.
        """
        _, _, event = heapq.heappop(self._heap)
        return event

    def peek(self) -> Event:
        """
        Return the earliest event without removing it.

        Returns
        -------
        Event  Earliest event in the queue.

        Raises
        ------
        IndexError  If the queue is empty.
        """
        return self._heap[0][2]


    # Utilities
    def is_empty(self) -> bool:
        """Check whether the queue is empty."""
        return len(self._heap) == 0

    def __len__(self) -> int:
        """Return the number of scheduled events."""
        return len(self._heap)