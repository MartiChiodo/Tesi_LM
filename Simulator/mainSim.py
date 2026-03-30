import sys
import os
# aggiunge la root del progetto (Tesi_LM)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import Simulator.config as config
from Simulator.scripts.warehousegeneration import *

def main():


    # --- Layout specification ---
    # These come from config.py — edit that file to change the scenario
    num_pods         = config.NUM_PODS
    num_skus         = config.NUM_SKUS
    num_robots       = config.NUM_ROBOTS
    num_workstations = config.NUM_WORKSTATIONS

    # --- Scenario specification ---
    # TODO: generate SKU distribution across pods using config.XI

    # --- Layout generation ---
    warehouse_initialization(num_pods, num_skus, num_robots, num_workstations, grid_rows = 2, grid_cols = 6, ws_order_cap = 1, ws_pod_cap = 1)


    # --- Simulation ---
    # sim = Simulator(config)
    # sim.run(config.TIME_HORIZON)


if __name__ == "__main__":
    main()