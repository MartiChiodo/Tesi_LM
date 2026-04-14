import numpy as np
import logging, os

from Simulator.scripts.core.enums import WorkstationPickingStatus, RobotStatus



class StatManager:
    """
    Collects and manages performance statistics for the warehouse simulation.

    The class tracks:
    - Resource utilization (robots and workstations)
    - Number of completed orders by size
    - Order flow time statistics
    - Average number of open orders per workstation (time-weighted)

    A warm-up period can be specified to exclude transient dynamics
    from the statistical analysis.
    """

    def __init__(self, warehouse, warm_up = 0):
        """
        Initialize the statistics manager.

        Parameters
        ----------
        warehouse : Warehouse
            The warehouse instance containing system resources.
        warm_up : float, optional
            Simulation time threshold before statistics collection starts.
        """

        self.WARM_UP = warm_up

        # Workstation utilization tracking (time spent in each state)
        self.workstation_picking_usage = np.zeros((len(warehouse.workstations), 2))
        self.ws_picking_last_clock = np.full(len(warehouse.workstations), -1)
        self.ws_picking_last_state = np.full(len(warehouse.workstations), -1, dtype=int)

        # Time-weighted average number of open orders per workstation
        self.workstation_avg_open_order = np.full(len(warehouse.workstations), 0)
        self.workstation_order_last_clock = np.full(len(warehouse.workstations), -1)
        self.workstation_order_last_value = np.full(len(warehouse.workstations), 0, dtype=int)

        # Robot utilization tracking
        self.robots_usage = np.zeros((len(warehouse.robots), 2))
        self.rb_usage_last_clock = np.full(len(warehouse.robots), -1)
        self.rb_usage_last_state = np.full(len(warehouse.robots), -1, dtype=int)

        # Order-level statistics
        self.counters_closed_orders = dict()      # number of completed orders per size
        self.cum_flow_time_orders = dict()        # cumulative flow time per size



    def update_statistic(self, type, info):
        """
        Update a specific statistic based on the event type.

        Parameters
        ----------
        type : str
            Identifier of the statistic to update:
            - "OFT": Order Flow Time
            - "WS_FREQ": Workstation utilization
            - "RB_FREQ": Robot utilization
            - "WS_AVG_OO": Average number of open orders (time-weighted)
        info : tuple or list
            Additional information required for the update.

        Notes
        -----
        - OFT: expects (order, completion_time)
        - WS_FREQ: expects (workstation_id, new_state, clock)
        - RB_FREQ: expects (robot_id, new_state, clock)
        - WS_AVG_OO: expects (workstation_id, new_value, clock)
        """
        
        match type:

            case "OFT":
                # Extract order size and timestamps
                os, at = info[0].order_size, info[0].arrival_time
                ct = info[1]

                if ct < self.WARM_UP:
                    return

                # Update counters and cumulative flow time
                if os in self.counters_closed_orders:
                    self.counters_closed_orders[os] += 1
                    self.cum_flow_time_orders[os] += ct - at
                else:
                    self.counters_closed_orders[os] = 1
                    self.cum_flow_time_orders[os] = ct - at


            case "WS_FREQ":
                # Workstation utilization update
                ws_id = info[0]
                new_state_id = info[1].value
                new_clock = info[2]

                if new_clock < self.WARM_UP:
                    self.ws_picking_last_state[ws_id] = int(new_state_id)
                else:
                    if (self.ws_picking_last_clock[ws_id] > -0.5) and (self.ws_picking_last_state[ws_id] > -0.5):
                        # Accumulate time spent in previous state
                        self.workstation_picking_usage[ws_id, self.ws_picking_last_state[ws_id]] += \
                            new_clock - self.ws_picking_last_clock[ws_id]
                    else:
                        # Initialization: assume initial state is IDLE
                        self.workstation_picking_usage[ws_id, WorkstationPickingStatus.IDLE.value] = 0
                        self.ws_picking_last_state[ws_id] = \
                            self.ws_picking_last_state[ws_id] \
                            if self.ws_picking_last_state[ws_id] > -0.5 \
                            else int(WorkstationPickingStatus.IDLE.value)

                    self.ws_picking_last_clock[ws_id] = new_clock
                    self.ws_picking_last_state[ws_id] = int(new_state_id)


            case "RB_FREQ":
                # Robot utilization update
                rb_id = info[0]
                new_state_id = info[1].value
                new_clock = info[2]

                if new_clock < self.WARM_UP:
                    self.rb_usage_last_state[rb_id] = int(new_state_id)
                else:
                    if (self.rb_usage_last_clock[rb_id] > -0.5) and (self.rb_usage_last_state[rb_id] > -0.5):
                        # Accumulate time spent in previous state
                        self.robots_usage[rb_id, self.rb_usage_last_state[rb_id]] += \
                            new_clock - self.rb_usage_last_clock[rb_id]
                    else:
                        # Initialization: assume initial state is IDLE
                        self.robots_usage[rb_id, RobotStatus.IDLE.value] = 0
                        self.rb_usage_last_state[rb_id] = \
                            self.rb_usage_last_state[rb_id] \
                            if self.rb_usage_last_state[rb_id] > -0.5 \
                            else int(RobotStatus.IDLE.value)

                    self.rb_usage_last_clock[rb_id] = new_clock
                    self.rb_usage_last_state[rb_id] = int(new_state_id)


            case "WS_AVG_OO":
                # Time-weighted average number of open orders per workstation
                ws_id, new_value, ct = info[0], info[1], info[2]

                if ct < self.WARM_UP:
                    self.workstation_order_last_value[ws_id] = new_value
                    self.workstation_order_last_clock[ws_id] = max(ct - self.WARM_UP, 0)
                    return
                
                # Close previous time interval (area accumulation)
                self.workstation_avg_open_order[ws_id] += \
                    (ct - self.workstation_order_last_clock[ws_id]) * \
                    self.workstation_order_last_value[ws_id]

                # Update state
                self.workstation_order_last_clock[ws_id] = ct
                self.workstation_order_last_value[ws_id] = new_value



    def return_statistics(self, output_path="Simulator/output/report.txt"):
        """
        Generate and export a summary report of all collected statistics.
        """

        lines = []

        def divider():
            lines.append("-" * 60)

        def header(t):
            lines.append(f"\n{'=' * 60}\n  {t}\n{'=' * 60}")

        def compute_util(usage):
            total_time = usage.sum(axis=1)
            busy_time = usage[:, 1]

            util = np.zeros_like(busy_time)
            mask = total_time > 0
            util[mask] = busy_time[mask] / total_time[mask]

            return util, total_time.sum(), busy_time.sum()
        

        def stats_table(name, usage):
            util, total_time, total_busy = compute_util(usage)

            header(name)

            if name == "WORKSTATIONS":
                lines.append(f"  {'ID':<6} {'Idle':>10} {'Busy':>10} {'Util':>8} {'Avg OO':>10}")
            else:
                lines.append(f"  {'ID':<6} {'Idle':>10} {'Busy':>10} {'Util':>8}")

            divider()

            for i in range(len(usage)):
                if name == "WORKSTATIONS":
                    avg_oo = self.workstation_avg_open_order[i]/(self.ws_picking_last_clock[i] - self.WARM_UP)
                    lines.append(
                        f"  {i:<6} {usage[i,0]:>10.2f} {usage[i,1]:>10.2f} "
                        f"{util[i]:>7.1%} {avg_oo:>10.2f}"
                    )
                else:
                    lines.append(
                        f"  {i:<6} {usage[i,0]:>10.2f} {usage[i,1]:>10.2f} "
                        f"{util[i]:>7.1%}"
                    )

            divider()

            global_util = total_busy / total_time if total_time > 0 else 0.0

            lines.append(f"  {'Mean':<6} {usage[:,0].mean():>10.2f} {usage[:,1].mean():>10.2f} {util.mean():>7.1%}")
            lines.append(f"  {'Std':<6} {usage[:,0].std():>10.2f} {usage[:,1].std():>10.2f} {util.std():>7.1%}")
            lines.append(f"  {'Global':<6} {'':>10} {'':>10} {global_util:>7.1%}")

        def orders_table():
            header("ORDERS BY SIZE")
            lines.append(f"  {'Size':<8} {'Closed':>8} {'Avg Flow':>12}")
            divider()

            sum_cum = 0.0
            sum_n = 0

            for size in sorted(self.counters_closed_orders):
                n = self.counters_closed_orders[size]
                cum = self.cum_flow_time_orders.get(size, 0.0)

                avg = cum / n if n > 0 else 0.0

                sum_cum += cum
                sum_n += n

                lines.append(f"  {size:<8} {n:>8} {avg:>12.2f}")

            divider()

            global_avg = sum_cum / sum_n if sum_n > 0 else 0.0
            lines.append(f"  {'Total':<8} {sum_n:>8} {global_avg:>12.2f}")

        stats_table("WORKSTATIONS", self.workstation_picking_usage)
        stats_table("ROBOTS", self.robots_usage)
        orders_table()

        lines.append("\n" + "=" * 60)

        report = "\n".join(lines)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(report)

        print(report)
        logging.info(f"Report saved to: {output_path}")



    def reset_statistics(self):
        """
        Reset all collected statistics.

        Clears:
        - Resource utilization data
        - Order-level counters and flow times

        Useful when running multiple simulation replications.
        """
        x = self.ws_picking_last_clock.shape[0]
        self.workstation_picking_usage = np.zeros((x, 2))
        self.ws_picking_last_clock = np.full(x, -1.0)
        self.ws_picking_last_state = np.full(x, -1.0)

        x = self.rb_usage_last_clock.shape[0]
        self.robots_usage = np.zeros((x, 2))
        self.rb_usage_last_clock = np.full(x, -1.0)
        self.rb_usage_last_state = np.full(x, -1.0)

        self.counters_closed_orders = dict()
        self.cum_flow_time_orders = dict()