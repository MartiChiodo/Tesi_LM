import heapq
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar
from enum import Enum, auto

### EVENTS

class EventType(Enum):
    """
    Enumeration of all event types used in the simulator.
    """

    # --- Outer simulator ---
    ARRIVAL_ORDER = auto()
    RUN_OPTIMIZER = auto()

    # --- Emulator ---
    RELEASE_TASK = auto()
    START_TASK = auto()
    ARRIVAL_POD_WST = auto()
    OPEN_ORDER = auto()
    START_PICKING = auto()
    END_PICKING = auto()
    CLOSE_ORDER = auto()
    RETURN_POD = auto()

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



### HEAP QUEUE - used for event queue and order backlog

T = TypeVar("T")

class PriorityQueue(Generic[T]):
    """
    Generic min-heap priority queue with stable ordering.

    Uses a monotonic counter to break ties, avoiding direct comparison
    between items. Supports any type T via a key function.

    Parameters
    ----------
    key : Callable[[T], float], optional
        Function mapping an item to its priority (lower = higher priority).
        Defaults to the identity function, so T must support float conversion
        or direct comparison if omitted.
    """

    def __init__(self, key: Callable[[T], float] = lambda x: float(x)) -> None:
        self._heap: list[tuple[float, int, T]] = []
        self._counter: int = 0
        self._key = key

    # Insertion method
    def push(self, item: T) -> T:
        """
        Add an item to the queue.

        Parameters
        ----------
        item : T    The item to enqueue.

        Returns
        -------
        T   The same item (for chaining / assignment convenience).

        Raises
        ------
        ValueError  If the derived priority is negative.
        """
        priority = self._key(item)
        if priority < 0:
            raise ValueError(f"Priority must be non-negative, got {priority}")

        heapq.heappush(self._heap, (priority, self._counter, item))
        self._counter += 1
        return item

    # Retrieval method
    def pop(self) -> T:
        """
        Remove and return the highest-priority (lowest key) item.

        Raises
        ------
        IndexError  If the queue is empty.
        """
        if self.is_empty():
            raise IndexError("pop from an empty priority queue")
        _, _, item = heapq.heappop(self._heap)
        return item

    def peek(self) -> T:
        """
        Return the highest-priority item without removing it.

        Raises
        ------
        IndexError  If the queue is empty.
        """
        if self.is_empty():
            raise IndexError("peek at an empty priority queue")
        return self._heap[0][2]

    def pop_many(self, n: int) -> list[T]:
        """
        Remove and return up to *n* items in priority order.

        Parameters
        ----------
        n : int     Maximum number of items to retrieve.
        """
        return [self.pop() for _ in range(min(n, len(self)))]


    # Utlities
    def is_empty(self) -> bool:
        """Return True if the queue contains no items."""
        return len(self._heap) == 0

    def __len__(self) -> int:
        """Return the number of items currently in the queue."""
        return len(self._heap)

    def __str__(self) -> str:
        if self.is_empty():
            return "PriorityQueue(empty)"
        lines = "\n".join(f"  {item}" for _, _, item in sorted(self._heap))
        return f"PriorityQueue(\n{lines}\n)"
    
    def __repr__(self) -> str:
        items = [str(item) for _, _, item in sorted(self._heap)]
        return f"PriorityQueue([{', '.join(items)}])"