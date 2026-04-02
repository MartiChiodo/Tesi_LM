from __future__ import annotations
from numpy.random import randint
import os, logging
import matplotlib.pyplot as plt

from Simulator.scripts.core.enums import PodStatus, WorkstationPickingStatus, RobotStatus
from Simulator.scripts.core.entities import *


# Layout constants
MARGIN      = 3
MIN_SPACING = 2


class Warehouse:
    """
    Physical representation of the warehouse.

    Holds all static and dynamic entities (pods, workstations, robots)
    and exposes utility methods for distance and travel time computation.

    Attributes
    ----------
    grid_rows : int               Number of pod rows in the storage area.
    grid_cols : int               Number of pod columns in the storage area.
    X : int                       Warehouse width  (grid units).
    Y : int                       Warehouse height (grid units).
    robot_speed : float           Robot speed in cells per minute.
    pods : list[Pod]              All pods in the warehouse.
    workstations : list[Workstation]  All workstations.
    robots : list[Robot]          All robots.
    """

    def __init__(
        self,
        num_pods: int,
        num_skus: int,
        num_robots: int,
        num_workstations: int,
        grid_rows: int,
        grid_cols: int,
        ws_order_cap: int,
        ws_pod_cap: int,
        robot_speed: float = 1.0,
        xi: float = 0.2,
    ) -> None:
        """
        Initialize the warehouse: validate parameters, compute grid dimensions,
        and generate pods, workstations, and robots.

        Parameters
        ----------
        num_pods : int          Total number of pods (must equal grid_rows * grid_cols).
        num_skus : int          Total number of SKUs (used for SKU distribution, TODO).
        num_robots : int        Total number of robots.
        num_workstations : int  Number of workstations.
        grid_rows : int         Number of pod rows.
        grid_cols : int         Number of pod columns.
        ws_order_cap : int      Max simultaneous open orders per workstation.
        ws_pod_cap : int        Max pods in the waiting queue per workstation.
        robot_speed : float     Robot speed in cells per minute.
        xi : float              Fraction of SKUs per pod (Boysen et al. 2017). TODO.
        """

        # Validation 
        assert num_pods == grid_rows * grid_cols, (
            f"Infeasible layout: num_pods ({num_pods}) must equal "
            f"grid_rows * grid_cols ({grid_rows * grid_cols})."
        )

        # Grid parameters
        self.grid_rows = grid_rows
        self.grid_cols = grid_cols
        self.robot_speed = robot_speed
        self.num_skus = num_skus

        # Warehouse physical dimensions (cell units)
        # One road is inserted every 2 pod rows/cols; MARGIN cells on each side
        self.X = grid_rows + ((grid_rows - 1) // 2) + 2 * MARGIN - 1
        self.Y = grid_cols + ((grid_cols - 1) // 2) + 2 * MARGIN - 1

        # Entity generation
        self.pods = self._generate_pods(num_pods, grid_rows, grid_cols)
        self.workstations = self._generate_workstations(num_workstations, ws_order_cap, ws_pod_cap)
        self.robots = self._generate_robots(num_robots)



    #  Private generation methods

    def _generate_pods(self, num_pods: int, grid_rows: int, grid_cols: int) -> list[Pod]:
        """
        Place pods on the storage grid.

        Pod IDs increase left-to-right along each row, then top-to-bottom.
        A road column is inserted every 2 pod columns; a road row every 2 pod rows.
        """
        pods = [None]*num_pods

        for col in range(grid_cols):
            for row in range(grid_rows):
                pod_id = col * grid_rows + row

                x_pod = MARGIN + row + (row // 2)       # vertical roads every 2 pods
                y_pod = self.Y - MARGIN - col - (col // 2)  # horizontal roads, top-down

                pods[pod_id] = Pod(
                        pod_id=pod_id,
                        status=PodStatus.IDLE,
                        home_position=(x_pod, y_pod),
                        sku_ids=[],   # TODO: SKU distribution
                    )

        return pods


    def _generate_workstations(
        self,
        num_ws: int,
        ws_order_cap: int,
        ws_pod_cap: int,
    ) -> list[Workstation]:
        """
        Place workstations along the warehouse perimeter.

        If all workstations fit symmetrically on the bottom edge (y = 0),
        they are placed there. Otherwise they are distributed anti-clockwise
        around the full perimeter.
        """
        workstations = [None]*num_ws

        def make_ws(ws_id: int, x: int, y: int) -> Workstation:
            return Workstation(
                workstation_id=ws_id,
                openorder_capacity=ws_order_cap,
                podqueue_capacity=ws_pod_cap,
                position=(x, y),
                open_orders=[],
                picking_status=WorkstationPickingStatus.IDLE,
                pod_queue=[],
                order_queue=[],
                pending_missions=[],
            )

        # Case 1: symmetric placement on bottom edge
        max_slots = (self.X - 2) // MIN_SPACING + 1

        if num_ws <= max_slots:
            center_x    = self.X // 2
            start_offset = -(num_ws // 2) * MIN_SPACING

            for ws_id in range(num_ws):
                x = center_x + start_offset + ws_id * MIN_SPACING
                workstations[ws_id] = make_ws(ws_id, x, 0)

            return workstations

        # Case 2: perimeter placement (anti-clockwise) 
        x_ws, y_ws = self.X // 2, 0

        for ws_id in range(num_ws):
            workstations[ws_id] = make_ws(ws_id, x_ws, y_ws)

            # Advance anti-clockwise
            if y_ws == 0:
                if x_ws + MIN_SPACING < self.X:
                    x_ws, y_ws = x_ws + MIN_SPACING, 0
                else:
                    x_ws, y_ws = self.X, MIN_SPACING

            elif x_ws == self.X:
                if y_ws + MIN_SPACING < self.Y:
                    x_ws, y_ws = self.X, y_ws + MIN_SPACING
                else:
                    x_ws, y_ws = self.X - MIN_SPACING, self.Y

            elif y_ws == self.Y:
                if x_ws - MIN_SPACING > 0:
                    x_ws, y_ws = x_ws - MIN_SPACING, self.Y
                else:
                    x_ws, y_ws = 0, self.Y - MIN_SPACING

            elif x_ws == 0:
                if y_ws - MIN_SPACING > 0:
                    x_ws, y_ws = 0, y_ws - MIN_SPACING
                else:
                    x_ws, y_ws = MIN_SPACING, 0

            else:
                raise ValueError(
                    f"Invalid workstation position during perimeter generation: ({x_ws}, {y_ws})"
                )

        return workstations


    def _generate_robots(self, num_robots: int) -> list[Robot]:
        """
        Assign random non-overlapping starting positions to robots.
        Positions are drawn uniformly from the interior of the warehouse.
        """
        robots = [None]*num_robots
        assigned_pos = set()   

        for robot_id in range(num_robots):
            x_r, y_r = randint(1, self.X - 1), randint(1, self.Y - 1)
            while (x_r, y_r) in assigned_pos:
                x_r, y_r = randint(1, self.X - 1), randint(1, self.Y - 1)
            assigned_pos.add((x_r, y_r))

            robots[robot_id] = Robot(
                    robot_id=robot_id,
                    position=(x_r, y_r),
                    current_task_id=None,
                    status=RobotStatus.IDLE,
                )

        return robots



    #  Distance and travel time

    @staticmethod
    def manhattan_distance(
        a: tuple[int, int],
        b: tuple[int, int],
    ) -> int:
        """
        Compute the Manhattan distance between two grid positions.

        Parameters
        ----------
        a : tuple[int, int]   Source position (x, y).
        b : tuple[int, int]   Destination position (x, y).

        Returns
        -------
        int  Manhattan distance |x_a - x_b| + |y_a - y_b|.
        """
        return abs(a[0] - b[0]) + abs(a[1] - b[1])


    def travel_time(
        self,
        a: tuple[int, int],
        b: tuple[int, int],
    ) -> float:
        """
        Estimate travel time between two grid positions.

        Computed as Manhattan distance divided by robot speed.
        Centralising this here means the rest of the codebase never
        needs to know about robot_speed directly.

        Parameters
        ----------
        a : tuple[int, int]   Source position (x, y).
        b : tuple[int, int]   Destination position (x, y).

        Returns
        -------
        float  Estimated travel time in minutes.
        """
        return self.manhattan_distance(a, b) / self.robot_speed



    #  Lookup helpers

    def get_pod(self, pod_id: int) -> Pod:
        """Return the Pod with the given ID. Raises KeyError if not found."""
        for pod in self.pods:
            if pod.pod_id == pod_id:
                return pod
        raise KeyError(f"Pod {pod_id} not found.")

    def get_workstation(self, ws_id: int) -> Workstation:
        """Return the Workstation with the given ID. Raises KeyError if not found."""
        for ws in self.workstations:
            if ws.workstation_id == ws_id:
                return ws
        raise KeyError(f"Workstation {ws_id} not found.")

    def get_robot(self, robot_id: int) -> Robot:
        """Return the Robot with the given ID. Raises KeyError if not found."""
        for robot in self.robots:
            if robot.robot_id == robot_id:
                return robot
        raise KeyError(f"Robot {robot_id} not found.")


    # Visualization
    
    def plot(
        self,
        save: bool = True,
        folder: str = r"Simulator\output\plots",
    ) -> None:
        """
        Plot the warehouse layout: pods, workstations, robots, and boundaries.
 
        Parameters
        ----------
        save : bool   If True, saves the figure as PNG and closes it.
                      If False, displays it interactively.
        folder : str  Destination folder when save=True.
        """
        scale = 0.8
        fig, ax = plt.subplots(figsize=(self.X * scale, self.Y * scale))
        ax.set_aspect('equal')
 
        # Pods — black squares
        for pod in self.pods:
            x, y = pod.home_position
            ax.add_patch(plt.Rectangle((x - 0.4, y - 0.4), 0.8, 0.8, fill=False, color='black'))
            ax.text(x, y, str(pod.pod_id), ha='center', va='center', fontsize=8, color='black')
 
        # Workstations — red circles
        for ws in self.workstations:
            x, y = ws.position
            ax.add_patch(plt.Circle((x, y), 0.5, fill=False, color='red'))
            ax.text(x, y, str(ws.workstation_id), ha='center', va='center', fontsize=8, color='red')
 
        # Robots — blue squares
        for robot in self.robots:
            x, y = robot.position
            ax.add_patch(plt.Rectangle((x - 0.25, y - 0.25), 0.5, 0.5, fill=False, color='blue'))
            ax.text(x, y, str(robot.robot_id), ha='center', va='center', fontsize=8, color='blue')
 
        # Warehouse border
        ax.add_patch(plt.Rectangle((0, 0), self.X, self.Y, fill=False, edgecolor='red', linewidth=2.5))
 
        ax.set_xlim(-2, self.X + 2)
        ax.set_ylim(-2, self.Y + 2)
        ax.set_xticks(range(0, self.X + 3))
        ax.set_yticks(range(0, self.Y + 3))
        ax.grid(True)
        plt.title("Warehouse Layout")
 
        if save:
            os.makedirs(folder, exist_ok=True)
            filename = os.path.join(folder, "warehouse_layout.png")
            plt.savefig(filename, dpi=300, bbox_inches='tight')
            plt.close(fig)
            logging.info(f"Warehouse layout saved to {filename}")
        else:
            plt.show()


    def __repr__(self) -> str:
        return (
            f"Warehouse("
            f"pod grid={self.grid_rows}x{self.grid_cols}, "
            f"size={self.X}x{self.Y}, "
            f"pods={len(self.pods)}, "
            f"workstations={len(self.workstations)}, "
            f"robots={len(self.robots)})"
        )