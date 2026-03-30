### SIMULATION CONFIGURATION
# All parameters are centralised here and imported by mainSim.py


# Layout 
NUM_PODS         = 12
NUM_SKUS         = 10
NUM_ROBOTS       = 10
NUM_WORKSTATIONS = 4

GRID_ROWS = 10          # number of rows in the warehouse grid
GRID_COLS = 10          # number of columns in the warehouse grid

ROBOT_SPEED = 1.0       # cells per minute


# Workstations
WS_ORDER_CAPACITY = 1   # M: max simultaneous open orders per workstation
WS_QUEUE_CAPACITY = 3   # max pods waiting in pod_queue per workstation


# SKU distribution (Boysen et al. 2017) 
XI = 0.05               # fraction of SKUs per pod (ξ ∈ {0.005, 0.05, 0.2})


# Order generation 
INTERARRIVAL_TIME = 5.0  # minutes between consecutive order arrivals (constant for now)


# Simulation control 
TIME_HORIZON  = 60 * 24  # total simulation time in minutes (1 day)
DELTA_T_OPT   = 15       # optimizer is called every DELTA_T_OPT minutes


# --- Stochasticity ---
# Travel time noise: actual_time = nominal_time + noise
# Distribution to be decided — placeholder values below
TRAVEL_NOISE_ENABLED = False
TRAVEL_NOISE_MEAN    = 0.0   # minutes
TRAVEL_NOISE_STD     = 1.0   # minutes (used if distribution is normal/lognormal)