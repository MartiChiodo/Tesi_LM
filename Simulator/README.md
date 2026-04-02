# Tesi_LM Project – Simulator Folder Overview

## Folder Structure


Tesi_LM/  
├── Simulator/  
│   ├── logs.log                   # Log file    
│   ├── run_simulation.py          # Entry point: reads config, builds warehouse, runs simulation    
│   ├── config.py                  # Numeric parameters for the simulation scenario  
│   └── output/  
│       └── plots/                 # Saved warehouse layout plots  
└── scripts/  
    ├── core/  
    │   ├── enums.py               # Enumerations: OrderStatus, RobotStatus, PodStatus, WorkstationPickingStatus  
    │   ├── events.py              # DES engine: EventType, Event, EventQueue  
    │   ├── entities.py            # Domain entities: Visit, Task, Order, Robot, Pod, Workstation  
    │   └── warehouse.py           # Warehouse class: layout, generation, utilities, plotting  
    │
    └── sim/  
        ├── simulator.py           # Core DES loop: clockmanagement, event dispatch, simulation execution  
        └── event_handler.py       # Event logic: one function per event type (arrival_order, start_task, etc.)  


---

## `run_simulation.py`

Entry point of the simulation:

- Configures logging
- Instantiates the Warehouse from config parameters
- Optionally plots the layout
- Creates Simulator instance
- Schedules initial events
- Runs the DES loop

---

## `config.py`

Holds all numeric configuration parameters for the simulation:

- `NUM_PODS`, `NUM_SKUS`, `NUM_ROBOTS`, `NUM_WORKSTATIONS`
- `GRID_ROWS`, `GRID_COLS`
- `ROBOT_SPEED`
- `WS_ORDER_CAPACITY`, `WS_QUEUE_CAPACITY`
- `XI` (SKU fraction per pod, Boysen et al. 2017)
- `INTERARRIVAL_TIME`, `TIME_HORIZON`, `DELTA_T_OPT`
- `TRAVEL_NOISE_ENABLED`, `TRAVEL_NOISE_MEAN`, `TRAVEL_NOISE_STD`

---

## `scripts/core/entities.py`

All domain entity dataclasses:

**Mission-related:**
- `Visit`: single stop in a task (workstation, order, SKUs, timing)
- `Task`: sequence of visits assigned to a robot/pod

**Order management:**
- `Order`: lifecycle (`BACKLOG → WAITING → OPEN → CLOSED`)

**Physical entities:**
- `Robot`: position, assigned task, status
- `Pod`: storage unit with SKU list and state
- `Workstation`: queues, capacities, picking status

---

## `scripts/core/warehouse.py`

Physical system representation and utilities:

**Warehouse class:**
- Generates pods, workstations, and robots
- Handles layout geometry (grid + roads + margins)
- Provides distance and travel time computations
- Ensures no overlapping positions (robots, pods)
- Offers lookup helpers (`get_pod`, `get_robot`, etc.)
- `plot(save, folder)`: visualize or save layout

---

## `scripts/core/enums.py`

Enumerations for discrete states:

- `OrderStatus`: `BACKLOG`, `WAITING`, `OPEN`, `CLOSED`
- `RobotStatus`: `IDLE`, `BUSY`
- `PodStatus`: `IDLE`, `BUSY`
- `WorkstationPickingStatus`: `IDLE`, `BUSY`

---

## `scripts/core/events.py`

Discrete Event Simulation (DES) primitives:

**EventType:**
- Outer simulator: `ARRIVAL_ORDER`, `RUN_OPTIMIZER`
- Emulator: `RELEASE_TASK`, `START_TASK`, `ARRIVAL_POD_WST`,
  `OPEN_ORDER`, `START_PICKING`, `END_PICKING`,
  `CLOSE_ORDER`, `RETURN_POD`

**Event:**
- `time` (absolute simulation time)
- `type` (`EventType`)
- `info` (optional payload)

**EventQueue:**
- Priority queue (min-heap)
- Ensures chronological execution
- Methods: `schedule()`, `pop()`, `peek()`, `is_empty()`

---

## `scripts/sim/simulator.py`

Main simulation engine:

- Maintains simulation clock
- Owns Warehouse and EventQueue
- Stores high-level data (`arrived_orders`, `scheduled_tasks`)
- Runs the DES loop:
  1. Pop next event
  2. Advance clock
  3. Dispatch event to handler

- Uses a dispatch table (`EventType → handler function`)
- No logic inside Event objects (clean separation)

---

## `scripts/sim/event_handler.py`

Event processing logic (core of the simulation behavior):

- One function per event type:
  - `arrival_order()`
  - `run_optimizer()`
  - `release_task()`
  - `start_task()`
  - `arrival_pod_wst()`
  - `open_order()`
  - `start_picking()`
  - `end_picking()`
  - `close_order()`
  - `return_pod()`

- Each handler:
  - Receives `(event, simulator)`
  - Updates Warehouse and simulation state
  - May schedule new events

- Clean separation between:
  - Decision logic (optimizer / policies)
  - Execution logic (robot, pod, workstation dynamics)

---

## Notes

- Warehouse replaces previous `SimulatorState` and `EmulatorState`
- Event-driven architecture ensures modularity and extensibility
- Clear separation:
  - `Event` → data
  - `EventQueue` → scheduling
  - `Simulator` → control flow
  - Handlers → system logic