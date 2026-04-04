# Tesi_LM Project – Simulator Folder Overview

## Folder Structure

```
Tesi_LM/
├── Simulator/
│   ├── run_simulation.py          # Entry point: reads config, builds warehouse, runs simulation
│   ├── config.py                  # Numeric parameters for the simulation scenario
│   └── output/
│       └── plots/                 # Saved warehouse layout plots
└── scripts/
    ├── core/
    │   ├── enums.py               # Enumerations: OrderStatus, RobotStatus, PodStatus, WorkstationPickingStatus, EventType
    │   ├── queues.py              # Priorityqueue definition
    │   └── entities.py            # Domain entities: Visit, Task, Order, Robot, Pod, Workstation, Warehouse, Event
    │
    ├── sim/
    │   ├── Simulator.py           # Core DES engine: state, clock, event dispatch, simulation loop
    │   └── event_handler.py       # Event logic: one function per event type
    │
    └── opt/
        └── policies.py            # Heuristic assignment policies (used when optimizer is disabled)
```

---

## `run_simulation.py`

Entry point of the simulation:

- Configures logging (writes to `logs.log`)
- Seeds the random number generator (`numpy.random.default_rng`)
- Instantiates `Warehouse` from `config` parameters
- Optionally plots the layout via `warehouse.plot()`
- Creates a `Simulator` instance and calls `sim.run(TIME_HORIZON)`

---

## `config.py`

Holds all numeric configuration parameters:

- `NUM_PODS`, `NUM_SKUS`, `NUM_ROBOTS`, `NUM_WORKSTATIONS`
- `GRID_ROWS`, `GRID_COLS`
- `ROBOT_SPEED` — cells per minute
- `WS_ORDER_CAPACITY`, `WS_QUEUE_CAPACITY`
- `PROB_1_ITEM_ORDER`, `GEO_DIST_PARAM_ORDER`, `INTERARRIVAL_TIME_ORDER` — order generation (Barnhart et al. 2024)
- `TIME_HORIZON`, `DELTA_T_OPT`
- `TRAVEL_NOISE_ENABLED`, `TRAVEL_NOISE_MEAN`, `TRAVEL_NOISE_STD`

---

## `scripts/core/entities.py`

All domain entity dataclasses and the `Warehouse` class.

**Mission-related:**
- `Visit` — single stop in a task: workstation, order, SKU list, desired arrival time `t_desired`
- `Task` — ordered sequence of visits assigned to a pod-robot pair; carries a scheduling `priority`

**Order management:**
- `Order` — customer order with full lifecycle (`BACKLOG → WAITING → OPEN → CLOSED`);
  fields: `order_id`, `arrival_time`, `num_skus`, `sku_required`, `assigned_ws`, `status`

**Physical entities:**
- `Robot` — position, current task ID, status (`IDLE` / `BUSY`)
- `Pod` — home position, SKU list, status (`IDLE` / `BUSY`)
- `Workstation` — queues, capacities, picking status; utility methods:
  - `has_open_slot()` — True if an order slot is free
  - `pod_queue_full()` — True if the pod queue is at capacity
  - `find_pod_for_order(order_id, active_tasks)` — returns the pod serving a given order

**Physical layout:**
- `Warehouse` — container for all entities; generates layout and exposes utilities:
  - `_generate_pods()` — places pods on grid with road spacing
  - `_generate_workstations()` — symmetric bottom-edge placement, or anti-clockwise perimeter fallback
  - `_generate_robots()` — random non-overlapping starting positions
  - `manhattan_distance(a, b)` — static method, `|Δx| + |Δy|`
  - `travel_time(a, b)` — Manhattan distance divided by `robot_speed`
  - `get_pod(id)`, `get_workstation(id)`, `get_robot(id)` — lookup helpers
  - `plot(save, folder)` — renders and optionally saves the layout as PNG

---

## `scripts/core/enums.py`

Enumerations for all discrete states and event types:

- `OrderStatus`: `BACKLOG`, `WAITING`, `OPEN`, `CLOSED`
- `RobotStatus`: `IDLE`, `BUSY`
- `PodStatus`: `IDLE`, `BUSY`
- `WorkstationPickingStatus`: `IDLE`, `BUSY`
- `EventType`: all DES event types (see `events.py` section below)

---

## `scripts/core/queues.py`

Priority queue definition:

**`PriorityQueue[T]`** — generic min-heap with stable ordering and optional O(1) id lookup:
- Parametric on item type `T` via a `key` function
- `id_attr` enables O(1) `get(id)` via internal index dictionary
- Methods: `push()`, `pop()`, `peek()`, `get()`, `pop_many()`, `is_empty()`
- Used for: event queue, arrived orders, scheduled tasks

---

## `scripts/sim/Simulator.py`

Core DES engine — owns all simulation state and drives the event loop.

**State (attributes):**
- `warehouse` — physical environment (`Warehouse` instance)
- `clock` — current simulation time
- `event_queue` — `PriorityQueue[Event]`, keyed by event time
- `arrived_orders` — `PriorityQueue[Order]`, keyed by `(status != BACKLOG, arrival_time)`; BACKLOG orders float to the top
- `scheduled_tasks` — `PriorityQueue[Task]`, keyed by `priority`
- `GEN` — numpy RNG instance (passed in, ensures reproducibility)
- `ORDER_GEN_PARAMS` — `[interarrival_time, prob_1_item_order, geo_dist_param]`
- `optimization` — flag: if False, uses heuristic policies; if True, routes through optimizer (TODO)

**Methods:**
- `run(time_horizon)` — schedules the first `ARRIVAL_ORDER` and runs the DES loop until time horizon
- `_build_dispatch()` — builds the `EventType → handler` dispatch table
- `_process_event(event, dispatch)` — calls the appropriate handler, passing `(event, self)`

**Order generation** follows Barnhart et al. 2024:
- Single-item order with probability `PROB_1_ITEM_ORDER`
- Multi-item order drawn from geometric distribution with parameter `GEO_DIST_PARAM_ORDER`
- SKUs sampled via `sample_sku()` in `utils.py` (truncated normal)

---

## `scripts/sim/event_handler.py`

Event processing logic — one function per event type, each receiving `(event, sim)`:

| Handler | Status | Responsibility |
|---|---|---|
| `arrival_order` | ✅ | Generates order, adds to `arrived_orders`, schedules next arrival; assigns to workstation if no optimizer |
| `run_optimizer` | TODO | Calls optimizer to produce tasks from backlog |
| `release_task` | TODO | Moves task from `scheduled_tasks` to emulator if capacity allows |
| `start_task` | TODO | Assigns idle robot to a released task |
| `arrival_pod_wst` | TODO | Handles pod arrival at workstation |
| `open_order` | TODO | Opens order when pod and slot are available |
| `start_picking` | TODO | Begins picking action at workstation |
| `end_picking` | TODO | Completes picking, updates order and pod state |
| `close_order` | TODO | Marks order closed when all SKUs are picked |
| `return_pod` | TODO | Sends pod back to home position, frees robot |

---

## `scripts/opt/policies.py`

Heuristic assignment policies used when `optimization=False`:

- `assign_order_to_workstation_policy(order, workstations)` — assigns an order to the workstation with the shortest `order_queue`

---

## Notes

- The RNG instance is passed explicitly through the call stack to ensure full reproducibility