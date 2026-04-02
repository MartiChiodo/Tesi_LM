import logging
import sys
import os

# Add the project root folder (the one containing Simulator) to the PATH
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import Simulator.config as config
from Simulator.scripts.core.warehouse import Warehouse  


def main():
    """
    Main entry point: initializes the warehouse and launches the simulation.
    """

    # --- Logger setup ---
    logging.basicConfig(
        filename=os.path.join(os.path.dirname(__file__), "logs.log"),
        encoding="utf-8",
        level=logging.INFO,
        datefmt="%H:%M:%S",
        filemode="w",
        format="%(asctime)s %(levelname)s: %(message)s",
    )

    # --- Warehouse initialization ---
    logging.info("Initializing warehouse ...")

    warehouse = Warehouse(
        num_pods         = config.NUM_PODS,
        num_skus         = config.NUM_SKUS,
        num_robots       = config.NUM_ROBOTS,
        num_workstations = config.NUM_WORKSTATIONS,
        grid_rows        = config.GRID_ROWS,
        grid_cols        = config.GRID_COLS,
        ws_order_cap     = config.WS_ORDER_CAPACITY,
        ws_pod_cap       = config.WS_QUEUE_CAPACITY,
        robot_speed      = config.ROBOT_SPEED,
        xi               = config.XI,
    )

    logging.info(f"Warehouse initialized: {warehouse}")

    # Visualization
    warehouse.plot(save=True)

    # --- TODO ---
    # SKU distribution among pods
    # Initialize SimulatorState and EmulatorState
    # Schedule initial events (ARRIVAL_ORDER, RUN_OPTIMIZER)
    # Run DES loop
    # event_handler.py con le funzioni per processare gli eventi in base al tipo
    # togliere gli append ma creare le liste come [None]*Num_elem

    ### SIMULATION
    # sim = Simulator(warehouse, config)
    # sim.run(config.TIME_HORIZON)


if __name__ == "__main__":
    main()
