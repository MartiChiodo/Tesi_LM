from enum import Enum, auto


class OrderStatus(Enum):
    """Lifecycle status of an order in the outer simulator."""
    BACKLOG  = auto()  # arrived but not yet considered by the optimizer
    WAITING  = auto()  # assigned to a workstation and queued there, not yet open
    OPEN     = auto()  # currently being served at a workstation (pod arrived, picking possible)
    CLOSED   = auto()  # all SKUs picked, order complete


class RobotStatus(Enum):
    """Status of a robot inside the emulator."""
    IDLE = auto()  # available, position known
    BUSY = auto()  # executing a task, carrying a pod


class PodStatus(Enum):
    """Status of a pod inside the emulator."""
    IDLE = auto()  # resting at its home cell in the grid
    BUSY = auto()  # in transit or waiting at a workstation


class WorkstationPickingStatus(Enum):
    """Whether a workstation is currently executing a picking action."""
    IDLE = auto()  # no picking in progress
    BUSY = auto()  # picking in progress on an arrived pod


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

