import heapq
from typing import Callable, Generic, TypeVar  



### HEAP QUEUE - used for event queue and order backlog

T = TypeVar("T")

class PriorityQueue(Generic[T]):
    """
    Generic min-heap priority queue with stable ordering and O(1) id lookup.

    Uses a monotonic counter to break ties, avoiding direct comparison
    between items. Supports any type T via a key function.

    If id_attr is specified, items are registered in an internal dictionary
    enabling O(1) lookup via get(). Otherwise get() performs an O(n) scan.

    Parameters
    ----------
    key : Callable[[T], float], optional
        Function mapping an item to its priority (lower = higher priority).
        Defaults to the identity function, so T must support float conversion
        or direct comparison if omitted.
    id_attr : str | None, optional
        Name of the attribute to use as unique identifier for O(1) lookup.
        E.g. 'order_id', 'task_id', 'event_id'. If None, get() is O(n).
    """

    def __init__(
        self,
        key: Callable[[T], float] = lambda x: float(x),
        id_attr: str | None = None,
    ) -> None:
        self._heap: list[tuple[float, int, T]] = []
        self._counter: int = 0
        self._key = key
        self._id_attr = id_attr
        self._index: dict[int, T] = {}

    
    # Internal helpers

    def _get_id(self, item: T) -> int | None:
        """Return the item's id if id_attr was specified, else None."""
        if self._id_attr is None:
            return None
        return getattr(item, self._id_attr, None)

    # Insertion

    def push(self, item: T) -> T:
        """
        Add an item to the queue.
        """
        priority = self._key(item)

        if isinstance(priority, (int, float)) and priority < 0:
            raise ValueError(f"Priority must be non-negative, got {priority}")

        heapq.heappush(self._heap, (priority, self._counter, item))
        self._counter += 1

        item_id = self._get_id(item)
        if item_id is not None:
            self._index[item_id] = item

        return item

    
    # Retrieval 

    def pop(self) -> T:
        """
        Remove and return the highest-priority (lowest key) item.
        """
        if self.is_empty():
            raise IndexError("pop from an empty priority queue")

        _, _, item = heapq.heappop(self._heap)

        item_id = self._get_id(item)
        if item_id is not None:
            self._index.pop(item_id, None)

        return item

    def peek(self) -> T:
        """
        Return the highest-priority item without removing it.
        """
        if self.is_empty():
            raise IndexError("peek at an empty priority queue")
        return self._heap[0][2]

    def get(self, id: int) -> T | None:
        """
        Return the item with the given id without removing it.

        O(1) if id_attr was specified at construction, O(n) fallback otherwise.
        """
        if self._id_attr is not None:
            return self._index.get(id)

        # O(n) fallback — no id_attr specified
        for _, _, item in self._heap:
            if getattr(item, self._id_attr or "", None) == id:
                return item
        return None

    def pop_many(self, n: int) -> list[T]:
        """
        Remove and return up to *n* items in priority order.
        """
        return [self.pop() for _ in range(min(n, len(self)))]

    
    # Utilities 

    def is_empty(self) -> bool:
        """Return True if the queue contains no items."""
        return len(self._heap) == 0

    def __len__(self) -> int:
        """Return the number of items currently in the queue."""
        return len(self._heap)

    def __iter__(self):
        """Iterate over items in priority order without modifying the queue."""
        for _, _, item in sorted(self._heap):
            yield item

    def __str__(self) -> str:
        if self.is_empty():
            return "PriorityQueue(empty)"
        lines = "\n".join(f"  {item}" for item in self)
        return f"PriorityQueue(\n{lines}\n)"

    def __repr__(self) -> str:
        return f"PriorityQueue([{', '.join(str(item) for item in self)}])"