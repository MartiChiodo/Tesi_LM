import logging
import sys
import os
# Add the project root folder (the one containing Simulator) to the PATH
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import Simulator.config as config
from Simulator.scripts.layout_generation import initialize_warehouse

def main():
    """
    Main entry point to generate warehouse layout and start simulation.
    """

    # Configuring logger
    logging.basicConfig(filename='Simulator\\logs.log', encoding='utf-8', level=logging.INFO, 
                        datefmt="%H:%M:%S", filemode="w", format="%(asctime)s %(levelname)s: %(message)s")

    # Layout specification from config.py 
    num_pods         = config.NUM_PODS
    num_skus         = config.NUM_SKUS
    num_robots       = config.NUM_ROBOTS
    num_workstations = config.NUM_WORKSTATIONS

    ### LAYOUT GENERATION
    # Returns pods and workstations lists
    logging.info("Initializing warehouse ...")
    pods, workstations, robots = initialize_warehouse(
        num_pods=num_pods,
        num_skus=num_skus,
        num_robots=num_robots,
        num_workstations=num_workstations,
        grid_rows=10,          # TODO: make dynamic / config-driven
        grid_cols=10,          # TODO: make dynamic / config-driven
        ws_order_cap=1,
        ws_pod_cap=1,
        xi=2,
        graphic = True
    )
    logging.info("End initializing warehouse.")



    ### TODO
    # SKU distribution among pods
    # event_handler.py con le funzioni per processare gli eventi in base al tipo

    ### SIMULATION
    # sim = Simulator(config)
    # sim.run(config.TIME_HORIZON)


if __name__ == "__main__":
    main()