import os, logging
import matplotlib.pyplot as plt
from numpy.random import randint

from Simulator.scripts.core.state import Pod, Workstation, Robot
from Simulator.scripts.core.enums import PodStatus, WorkstationPickingStatus, RobotStatus


MARGIN = 3
MIN_SPACING = 2


### WAREHOUSE INITIALIZATION
def initialize_warehouse(
    num_pods: int,
    num_skus: int,
    num_robots: int,
    num_workstations: int,
    grid_rows: int,
    grid_cols: int,
    ws_order_cap: int,
    ws_pod_cap: int,
    xi: float = 0.2,
    graphic = False
):
    """
    Initialize warehouse layout including pods and workstations.

    Parameters
    ----------
    num_pods : int          Total number of pods.
    num_skus : int          Total number of SKUs (currently unused).
    num_robots : int        Total number of robots (currently unused).
    num_workstations : int  Number of workstations.
    grid_rows : int         Number of pod rows.
    grid_cols : int         Number of pod columns.
    ws_order_cap : int      Workstation order capacity.
    ws_pod_cap : int        Workstation pod queue capacity.
    xi : float              Placeholder parameter (unused). #TODO
    graphic : bool          Bool to enable graphic

    Returns
    -------
    tuple[list[Pod], list[Workstation]]  Generated pods and workstations.
    """

    # Feasibility check
    assert num_pods == grid_rows * grid_cols, \
        "Infeasible layout: num_pods must match grid dimensions."

    # Compute warehouse dimensions
    X = grid_rows + ((grid_rows-1) // 2) + 2 * MARGIN
    Y = grid_cols + ((grid_cols-1) // 2) + 2 * MARGIN
    X, Y = X - 1, Y - 1


    ### Pod Generation
    pods: list[Pod] = []

    for col in range(grid_cols):
        for row in range(grid_rows):
            # pod_id increases left-to-right along the row, then top-to-bottom
            pod_id = col * grid_rows + row

            # Top-left corner = row 0, col 0
            x_pod = MARGIN + row + (row // 2)      # add vertical roads every 2 pods
            y_pod = Y - MARGIN - col - (col // 2)  # add horizontal roads every 2 rows, top-down

            pod = Pod(
                pod_id=pod_id,
                status=PodStatus.IDLE,
                home_position=(x_pod, y_pod),
                sku_ids=[] # TODO
            )
            pods.append(pod)



    ### Workstation Generation
    workstations = generate_workstations_adapt(
        X, Y, num_workstations, ws_order_cap, ws_pod_cap
    )


    ### Robot Generation
    robots: list[Robot] = []

    assigned_pos = set(tuple[int, int])
    for id_r in range(num_robots):

        # assign random starting positions to robots, ensuring no two robots overlap
        x_r, y_r = randint(1, X-1), randint(1, Y-1)
        while (x_r, y_r) in assigned_pos:
            x_r, y_r = randint(1, X-1), randint(1, Y-1)
        assigned_pos.add((x_r, y_r)) 

        r = Robot(
            robot_id = id_r,
            position = (x_r, y_r),
            current_task_id = None,
            status = RobotStatus.IDLE
        )

        robots.append(r)

            

    ### Visualization
    if graphic:
        plot_warehouse(pods, workstations, robots, X, Y)

    return pods, workstations, robots



### WORKSTATION GENERATION - support function
def generate_workstations_adapt(
    X: int,
    Y: int,
    num_ws: int,
    ws_order_cap: int,
    ws_pod_cap: int
):
    """
    Generate workstation positions with symmetric placement.

    If all workstations fit on one side, they are placed symmetrically
    along the bottom edge. Otherwise, they are distributed along the
    perimeter in anti-clockwise order.

    Parameters
    ----------
    X : int                Warehouse width.
    Y : int                Warehouse height.
    num_ws : int           Number of workstations.
    ws_order_cap : int     Order capacity per workstation.
    ws_pod_cap : int       Pod queue capacity per workstation.

    Returns
    -------
    list[Workstation]  Generated workstations.
    """

    workstations: list[Workstation] = []

    # CASE 1: Symmetric placement on bottom side

    max_slots = (X - 2) // MIN_SPACING + 1

    if num_ws <= max_slots:
        center_x = X // 2
        start_offset = -(num_ws // 2) * MIN_SPACING

        for i in range(num_ws):
            x = center_x + start_offset + i * MIN_SPACING
            y = 0

            ws = Workstation(
                workstation_id=i,
                openorder_capacity=ws_order_cap,
                podqueue_capacity=ws_pod_cap,
                position=(x, y),
                open_orders=[],
                picking_status=WorkstationPickingStatus.IDLE,
                pod_queue=[],
                order_queue=[],
                pending_missions=[]
            )

            workstations.append(ws)

        return workstations


    # CASE 2: Perimeter placement (fallback)

    x_ws, y_ws = X // 2, 0

    for ws_id in range(num_ws):
        ws = Workstation(
            workstation_id=ws_id,
            openorder_capacity=ws_order_cap,
            podqueue_capacity=ws_pod_cap,
            position=(x_ws, y_ws),
            open_orders=[],
            picking_status=WorkstationPickingStatus.IDLE,
            pod_queue=[],
            order_queue=[],
            pending_missions=[]
        )

        workstations.append(ws)

        # Move anti-clockwise
        if y_ws == 0:
            if x_ws + MIN_SPACING < X:
                x_new, y_new = x_ws + MIN_SPACING, 0
            else:
                x_new, y_new = X, MIN_SPACING

        elif x_ws == X:
            if y_ws + MIN_SPACING < Y:
                x_new, y_new = X, y_ws + MIN_SPACING
            else:
                x_new, y_new = X - MIN_SPACING, Y

        elif y_ws == Y:
            if x_ws - MIN_SPACING > 0:
                x_new, y_new = x_ws - MIN_SPACING, Y
            else:
                x_new, y_new = 0, Y - MIN_SPACING

        elif x_ws == 0:
            if y_ws - MIN_SPACING > 0:
                x_new, y_new = 0, y_ws - MIN_SPACING
            else:
                x_new, y_new = MIN_SPACING, 0

        else:
            raise ValueError("Invalid workstation position during generation.")

        x_ws, y_ws = x_new, y_new

    return workstations



### VISUALIZATION - support function
def plot_warehouse(pods, workstations, robots, X, Y, save: bool = True, folder: str = r"Simulator\output\plots"):
    """
    Plot warehouse layout including pods and workstations.
    If save=True, saves the figure as PNG in the specified folder.

    Parameters
    ----------
    pods : list[Pod]                List of pods.
    workstations : list[Workstation] List of workstations.
    X : int                         Warehouse width.
    Y : int                         Warehouse height.
    save : bool                     Whether to save the plot instead of showing it.
    folder : str                    Folder to save the plot in.
    """

    # Maintain aspect ratio and scale
    scale = 0.8  # optional: scale factor for padding
    fig_width = X * scale
    fig_height = Y * scale

    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.set_aspect('equal')

    # Pods 
    for pod in pods:
        x, y = pod.home_position
        square = plt.Rectangle((x - 0.4, y - 0.4), 0.8, 0.8, fill=False, color = 'black')
        ax.add_patch(square)
        ax.text(x, y, str(pod.pod_id), ha='center', va='center', fontsize=8, color='black')

    # Workstations 
    for ws in workstations:
        x, y = ws.position
        circle = plt.Circle((x, y), 0.5, fill=False, color = 'red')
        ax.add_patch(circle)
        ax.text(x, y, str(ws.workstation_id), ha='center', va='center', fontsize=8, color='red')

    # Robots
    for r in robots:
        x,y = r.position
        square = plt.Rectangle((x - 0.25, y - 0.25), 0.5, 0.5, fill=False, color = 'blue')
        ax.add_patch(square)
        ax.text(x, y, str(r.robot_id), ha='center', va='center', fontsize=8, color='blue')

    # Warehouse boundaries
    border = plt.Rectangle((0, 0), X, Y, fill=False, edgecolor='red', linewidth=2.5)
    ax.add_patch(border)

    ax.set_xlim(-2, X + 2)
    ax.set_ylim(-2, Y + 2)
    ax.set_aspect('equal')

    ax.set_xticks(range(0, int(X) + 3))
    ax.set_yticks(range(0, int(Y) + 3))
    ax.grid(True)

    plt.title("Warehouse Layout")

    if save:
        # Create folder if it does not exist
        os.makedirs(folder, exist_ok=True)
        # Generate a unique filename
        filename = os.path.join(folder, f"warehouse_layout.png")
        plt.savefig(filename, dpi=300, bbox_inches='tight')
        plt.close(fig)  # Close figure to free memory
        logging.info(f"Warehouse layout saved to {filename}")
    else:
        plt.show()