from Simulator.scripts.core.events import EventType, EventQueue, Event
from Simulator.scripts.core.state import SimulatorState, EmulatorState

def process_event(event: Event, sim_state: SimulatorState, emu_state: EmulatorState):
    """
    Process a single event based on its type, updating simulator/emulator state.
    """
    if event.type == EventType.ARRIVAL_ORDER:
        # A new order arrives → aggiungilo al backlog
        sim_state.backlog_orders.append(event.info['order'])
    
    elif event.type == EventType.RUN_OPTIMIZER:
        # Call optimizer → generate tasks and add to mission_queue
        generate_tasks(sim_state)
    
    elif event.type == EventType.RELEASE_TASK:
        # Move task from mission_queue to emulator's active tasks if pod queue has space
        release_task_to_emulator(event.info, sim_state, emu_state)
    
    elif event.type == EventType.START_TASK:
        # Assign a robot to a released task
        start_task(event.info, emu_state)
    
    # continua con gli altri tipi di evento...