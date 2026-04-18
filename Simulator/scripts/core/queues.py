import heapq
from typing import Callable, Generic, TypeVar

T = TypeVar("T")

_BLOAT_FACTOR = 2  # compact() triggers when heap size > BLOAT_FACTOR * active_size


class PriorityQueue(Generic[T]):
    """
    Generic min-heap priority queue with lazy deletion and O(1) id-based lookup.

    Internally uses a (priority, counter, item) heap. Stale entries left by
    ``update`` and ``remove`` are skipped on extraction rather than eagerly
    removed, keeping mutation O(log n). Physical cleanup is deferred to
    ``compact()``, called automatically when heap bloat exceeds ``_BLOAT_FACTOR``.

    Parameters
    ----------
    key : Callable[[T], float]
        Maps an item to its priority scalar (lower = higher priority).
    id_attr : str | None
        Attribute name used as unique item identifier. Required for
        ``update``, ``remove``, and O(1) ``get``. If None, those operations
        either raise or fall back to O(n) scan.
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
        self.active_size: int = 0

    #  Internal 

    def _id(self, item: T) -> int | None:
        """Return item id if id_attr is set, else None."""
        return getattr(item, self._id_attr, None) if self._id_attr else None

    def _is_live(self, item: T) -> bool:
        """True if item is still the current version in the index."""
        item_id = self._id(item)
        return item_id is None or self._index.get(item_id) is item

    def _push_raw(self, item: T) -> None:
        heapq.heappush(self._heap, (self._key(item), self._counter, item))
        self._counter += 1

    def _maybe_compact(self) -> None:
        if len(self._heap) > _BLOAT_FACTOR * max(self.active_size, 1):
            self.compact()

    #  Insertion 

    def push(self, item: T) -> T:
        """Add *item* to the queue. Raises ValueError on negative priority."""
        priority = self._key(item)
        if isinstance(priority, (int, float)) and priority < 0:
            raise ValueError(f"Priority must be non-negative, got {priority}")

        self._push_raw(item)
        self.active_size += 1

        item_id = self._id(item)
        if item_id is not None:
            self._index[item_id] = item

        return item

    def update(self, item: T) -> T:
        """
        Replace the existing entry for *item* (matched by id) with a new one.

        The old heap entry is lazily invalidated; the new one is pushed.
        Raises ValueError if id_attr is not set or item has no valid id.
        """
        if self._id_attr is None:
            raise ValueError("update() requires id_attr to be set")

        item_id = self._id(item)
        if item_id is None:
            raise ValueError("Item must have a valid id")

        if item_id in self._index:
            self.active_size -= 1  # evict old logical entry

        self._index[item_id] = item
        self._push_raw(item)
        self.active_size += 1

        self._maybe_compact()
        return item

    #  Removal 

    def pop(self) -> T:
        """Remove and return the highest-priority (lowest key) live item."""
        while self._heap:
            _, _, item = heapq.heappop(self._heap)
            if not self._is_live(item):
                continue
            item_id = self._id(item)
            if item_id is not None:
                self._index.pop(item_id, None)
            self.active_size -= 1
            return item
        raise IndexError("pop from an empty priority queue")

    def remove(self, id: int) -> None:
        """
        Remove item by id in O(1) via lazy deletion.

        The heap entry remains physically until the next pop/compact; it will
        be silently skipped. Raises KeyError if id is not found.
        """
        if self._id_attr is None:
            raise ValueError("remove() requires id_attr to be set")
        if id not in self._index:
            raise KeyError(f"No item with id={id}")
        self._index.pop(id)
        self.active_size -= 1

    def pop_many(self, n: int) -> list[T]:
        """Remove and return up to *n* items in priority order."""
        return [self.pop() for _ in range(min(n, self.active_size))]

    #  Lookup 

    def peek(self) -> T:
        """Return the highest-priority live item without removing it."""
        while self._heap:
            _, _, item = self._heap[0]
            if self._is_live(item):
                return item
            heapq.heappop(self._heap)
        raise IndexError("peek at an empty priority queue")

    def get(self, id: int) -> T | None:
        """
        Return item by id without removing it.

        O(1) if id_attr is set (index lookup), O(n) linear scan otherwise.
        """
        if self._id_attr is not None:
            return self._index.get(id)
        for _, _, item in self._heap:
            if getattr(item, self._id_attr or "", None) == id:
                return item
        return None

    #  Maintenance 

    def compact(self) -> None:
        """
        Physically purge stale heap entries.

        O(m log m) where m is the current heap size. Called automatically by
        ``update`` when heap size exceeds ``_BLOAT_FACTOR * active_size``.
        """
        self._heap = [
            entry for entry in self._heap
            if self._is_live(entry[2])
        ]
        heapq.heapify(self._heap)

    #  Utilities 

    def is_empty(self) -> bool:
        """True if no live items remain."""
        while self._heap:
            if self._is_live(self._heap[0][2]):
                return False
            heapq.heappop(self._heap)
        return True

    def __len__(self) -> int:
        return self.active_size

    def __iter__(self):
        """Yield live items in priority order without modifying the queue."""
        for _, _, item in sorted(self._heap):
            if self._is_live(item):
                yield item

    def __str__(self) -> str:
        if self.is_empty():
            return "PriorityQueue(empty)"
        return "PriorityQueue(\n" + "\n".join(f"  {i}" for i in self) + "\n)"

    def __repr__(self) -> str:
        return f"PriorityQueue([{', '.join(str(i) for i in self)}])"