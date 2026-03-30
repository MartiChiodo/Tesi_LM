import heapq
from dataclasses import dataclass, field
from typing import Any


# All event types recognised by the simulator
EVENT_TYPES = frozenset({
    # --- Outer simulator ---
    "arrival_order",   # a new order enters the backlog
    "run_optimizer",   # fires every Δt_opt

    # --- Emulator ---
    "release_task",    # a pending mission is released (if pod_queue has a free slot)
    "start_task",      # an idle robot picks up a released task
    "arrival_pod_wst", # pod arrives at a workstation
    "open_order",      # workstation opens the next order in its queue
    "start_picking",   # SKU picking begins on an arrived pod
    "end_picking",     # picking action completed
    "close_order",     # order completed (all SKUs picked)
    "return_pod",      # robot carries pod back to its home cell
})


@dataclass
class Event:
    """
    A single DES event.

    time    — simulation time at which the event occurs
    type    — event type string (must be in EVENT_KINDS)
    info — arbitrary data needed by the event handler (e.g. pod_id, order_id)
    """
    time:    float
    type:    str
    info: Any = None

    def __post_init__(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(f"Unknown event tyoe: '{self.type}'")


class EventQueue:
    """
    Priority queue for DES events, ordered by simulation time.
    Ties are broken by a monotonically increasing counter so that
    Event objects are never compared directly (avoids dataclass comparison issues).
    """

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, Event]] = []
        self._counter: int = 0

    def schedule(self, time: float, type: str, info: Any = None) -> Event:
        """Create an event and push it onto the queue. Returns the Event."""
        event = Event(time=time, type=type, info=info)
        heapq.heappush(self._heap, (time, self._counter, event))
        self._counter += 1
        return event

    def pop(self) -> Event:
        """Remove and return the earliest event. Raises IndexError if empty."""
        _, _, event = heapq.heappop(self._heap)
        return event

    def peek(self) -> Event:
        """Return the earliest event without removing it. Raises IndexError if empty."""
        return self._heap[0][2]

    def is_empty(self) -> bool:
        return len(self._heap) == 0

    def __len__(self) -> int:
        return len(self._heap)
