### SIMULATION CONFIGURATION
# All parameters are centralised here and imported by run_simulation.py


# Warehouse Layout 
NUM_PODS         = 100
NUM_SKUS         = 1000
NUM_ROBOTS       = 20
NUM_WORKSTATIONS = 9

GRID_ROWS = 10       # number of rows for the pod grid
GRID_COLS = 10       # number of columns for the pod grid

ROBOT_SPEED = 30.0       # cells per minute (1 m/s)


# Workstations
WS_ORDER_CAPACITY = 1   # M: max simultaneous open orders per workstation
WS_WORKLOAD_CAPACITY = 3   # max pods waiting in pod_queue per workstation 
                        # (more of an indication on how many active tasks reòlated to each ws simultaneosly)


# Parameters for order generation (Barnhart et al. 2024 approach)
PROB_1_ITEM_ORDER = 0.5
GEO_DIST_PARAM_ORDER = 0.65      # takes value in {0.25, 0.35, 0.45, 0.65}
INTERRARIVAL_TIME_ORDER = 0.34   # equivalent of 175 orders per hour (unit time : minutes)



# Simulation control 
TIME_HORIZON  = 60   # total simulation time in minutes (1 day)
DELTA_T_OPT   = 15       # optimizer is called every DELTA_T_OPT minutes


# Pikcing time
POD_PROCESS_TIME = 5/60
ITEM_PROCESS_TIME = 5/60



# --- Stochasticity ---
# Travel time noise: actual_time = nominal_time + noise
# Distribution to be decided — placeholder values below
TRAVEL_NOISE_ENABLED = False
TRAVEL_NOISE_MEAN    = 0.0   # minutes
TRAVEL_NOISE_STD     = 1.0   # minutes (used if distribution is normal/lognormal)