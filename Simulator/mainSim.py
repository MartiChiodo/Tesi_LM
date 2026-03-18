import config


def main():

    # --- Layout specification ---
    # These come from config.py — edit that file to change the scenario
    num_pods         = config.NUM_PODS
    num_robots       = config.NUM_ROBOTS
    num_workstations = config.NUM_WORKSTATIONS

    # --- Scenario specification ---
    # TODO: generate SKU distribution across pods using config.XI

    # --- Layout generation ---
    # TODO: place pods, robots and workstations on the grid
    #       and pre-compute pod-to-workstation distances

    # --- Simulation ---
    # sim = Simulator(config)
    # sim.run(config.TIME_HORIZON)


if __name__ == "__main__":
    main()