import os, sys, logging
import numpy.random 

# Add the project root folder (the one containing Simulator) to the PATH
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import Simulator.config as config
from Simulator.scripts.core.warehouse import Warehouse  
from Simulator.scripts.sim.Simulator import Simulator


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

    # Seed
    gen = numpy.random.default_rng(12345)


    # Warehouse initialization 
    logging.info("Initializing warehouse ...")

    warehouse = Warehouse(
        random_generator                = gen,
        num_pods                        = config.NUM_PODS,
        num_skus                        = config.NUM_SKUS,
        num_robots                      = config.NUM_ROBOTS,
        num_workstations                = config.NUM_WORKSTATIONS,
        grid_rows                       = config.GRID_ROWS,
        grid_cols                       = config.GRID_COLS,
        ws_order_capacity               = config.WS_ORDER_CAPACITY,
        ws_released_task_capacity       = config.WS_WORKLOAD_CAPACITY,
        robot_speed                     = config.ROBOT_SPEED,
        pod_process_time                = config.POD_PROCESS_TIME,
        item_process_time               = config.ITEM_PROCESS_TIME
    )
 
    logging.info(f"Warehouse initialized: {warehouse}")

    # Visualization
    # warehouse.plot(save=True)

    # --- TODO ---
    # SKU distribution among pods
    # Define RUN_OPTIMIZER handler
    # Creare uno StatManager per le statistiche
    # Sistemare la configurazione dei parametri

    ### SIMULATION
    sim = Simulator(
        random_generator = gen,
        order_gen_config =[config.INTERRARIVAL_TIME_ORDER, config.PROB_1_ITEM_ORDER, config.GEO_DIST_PARAM_ORDER],
        warehouse = warehouse
    )
    sim.run(60)


if __name__ == "__main__":
    main()
