from math import floor
import matplotlib.pyplot as plt

from Simulator.scripts.classes.events import Event, EventQueue
from Simulator.scripts.classes.state import Visit, Task, Order, SimulatorState, Pod, Robot, Workstation, EmulatorState
from Simulator.scripts.classes.enums import OrderStatus, RobotStatus, PodStatus, WorkstationPickingStatus

MARGIN = 3
MIN_SPACING = 2

def warehouse_initialization(num_pods,num_skus, num_robots, num_workstations, grid_rows, grid_cols, ws_order_cap, ws_pod_cap, xi = 0.2):

    # Check if the warehouse is big enough for num_pods
    assert num_pods == grid_rows * grid_cols, "The  layout of the warehouse is not feasibile (check number of pods, grid_rows, grid_cols)."

    # X, Y are the sizes of the warehouse accounting for the paths and the space for the workstations (3 squares of margins in each direction)
    tempX = 2*MARGIN + grid_rows + ((grid_rows)/2 -1) * ((grid_rows +1)%2) + floor(grid_rows)*(grid_rows%2)
    tempY = 2*MARGIN + grid_cols + ((grid_cols)/2 -1)* ((grid_cols +1)%2) + floor(grid_cols)*(grid_cols%2)
    X, Y = max(tempX, tempY) - 1, min(tempX, tempY) - 1

    # Instantiating the pods and their locations
    pods = []
    x_pod, y_pod = MARGIN, Y-MARGIN
    for id_pod in range(num_pods):
        p = Pod(
                pod_id =id_pod,
                status =PodStatus.IDLE,
                home_position = (x_pod, y_pod),
                sku_ids = []  # TODO
            )

        pods.append(p)

        # Updating x_pod, y_pod
        x_pod_new, y_pod_new = -1, -1
        if x_pod + 1* ((id_pod+1)%2)  + 2* ((id_pod)%2)> X - MARGIN:
            x_pod_new = MARGIN
            y_pod_new = y_pod - 2 if (id_pod + 1) % (2*grid_cols) == 0 else y_pod -1 
        else:
            x_pod_new = x_pod + 2 if id_pod % 2 == 1 else x_pod+1
            y_pod_new = y_pod

        x_pod, y_pod = x_pod_new, y_pod_new


    # Generating workstations and their positions
    workstations = generate_workstations_adaptive(X, Y, num_workstations, ws_order_cap, ws_pod_cap)
    

    # Plot
    plot_warehouse(pods, workstations, X, Y)

    return



def generate_workstations_adaptive(X, Y, num_workstations, ws_order_cap, ws_pod_cap):
    """
    Generate adaptive position of workstations based on given parameters and constraints.
     X - width of the warehouse
     Y - height of the warehouse
     num_workstation - number of workstations to generate
     min_spacing - minimum spacing between workstations
     ws_order_cap - open order capacity of workstations
     ws_pod_cap - pod capacity of workstations
     
    Return List of generated workstations
    """

    workstations = []

    x_ws = floor(X/2)
    y_ws = 0
    for id_ws in range(num_workstations):
        w = Workstation(
                    workstation_id = id_ws,
                    openorder_capacity = ws_order_cap,
                    podqueue_capacity = ws_pod_cap,
                    position = (x_ws, y_ws),
                    open_orders = [],
                    picking_status = WorkstationPickingStatus.IDLE,
                    pod_queue = [],
                    order_queue = [],
                    pending_missions= []
                )
        
        workstations.append(w)

        # Updating the coordinates (moving anti-clock wise)
        x_ws_new, y_ws_new = -1, -1

        if y_ws == 0: 
            if x_ws + MIN_SPACING < X - 1:
                x_ws_new, y_ws_new = x_ws + MIN_SPACING, 0
            else:
                x_ws_new, y_ws_new = X, 2
        if x_ws == X:
            if y_ws + MIN_SPACING < Y - 1:
                x_ws_new, y_ws_new = X, y_ws + MIN_SPACING
            else:
                x_ws_new, y_ws_new = X - MIN_SPACING, Y
        if y_ws == Y:
            if x_ws - MIN_SPACING > 1:
                x_ws_new, y_ws_new = x_ws - MIN_SPACING, Y
            else:
                x_ws_new, y_ws_new = 0, Y - MIN_SPACING
        if x_ws == 0:
            if y_ws - MIN_SPACING > 1:
                x_ws_new, y_ws_new = X, y_ws - MIN_SPACING
            else:
                x_ws_new, y_ws_new = X + MIN_SPACING, 0

        assert x_ws_new > -0.5 and y_ws_new > -0.5, "The layout of the warehouse is not feasible (check te proportion between num_pods and num_workstation)."

        x_ws, y_ws = x_ws_new, y_ws_new

    return workstations



def plot_warehouse(pods, workstations, X, Y):
    fig, ax = plt.subplots(figsize=(8, 8))

    # Plot pods (quadrati)
    for pod in pods:
        x, y = pod.home_position
        square = plt.Rectangle((x - 0.4, y - 0.4), 0.8, 0.8, fill=False)
        ax.add_patch(square)
        ax.text(x, y, str(pod.pod_id), ha='center', va='center', fontsize=8)

    # Plot workstations (cerchi)
    for ws in workstations:
        x, y = ws.position
        circle = plt.Circle((x, y), 0.5, fill=False)
        ax.add_patch(circle)
        ax.text(x, y, str(ws.workstation_id), ha='center', va='center', fontsize=8, color='red')

    # Box rossa del perimetro
    warehouse_border = plt.Rectangle(
        (0, 0), X, Y,
        fill=False,
        edgecolor='red',
        linewidth=2.5
    )
    ax.add_patch(warehouse_border)

    # Configurazione griglia
    ax.set_xlim(0, X + 2)
    ax.set_ylim(0, Y + 2)
    ax.set_aspect('equal')

    ax.set_xticks(range(0, int(X) + 3))
    ax.set_yticks(range(0, int(Y) + 3))
    ax.grid(True)

    plt.title("Warehouse Layout")
    plt.show()