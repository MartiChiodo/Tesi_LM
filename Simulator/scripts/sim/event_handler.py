from Simulator.scripts.core.entities import Order
from Simulator.scripts.core.events import EventType, Event
from Simulator.scripts.core.enums import OrderStatus, RobotStatus, PodStatus, WorkstationPickingStatus


def arrival_order(event, sim):

    id = len(sim.arrived_orders)
    ns : int
    list_s : list[int]

    ### Order generation (as in Barnhart2024)
    r = sim.GEN.random()    # value in [0,1)
    if r < sim.ORDER_GEN_PARAMS[1]:
        ns = 1
    else:
        ns = sim.GEN.geometric(p = sim.ORDER_GEN_PARAMS[2]) + 2

    list_s = [0]*ns

    for i in range(ns):

        id_s = 0
        done = False
        N = sim.warehouse.num_skus

        while not done:
            id_s = sim.GEN.normal(0.5*N, (0.5*N)/3)
            id_s = int(id_s)
            done = (id_s > -0.5 and id_s < N)

        list_s[i] = id_s

    # Adding order to backlog
    o = Order(
        order_id=id, 
        num_skus=ns, 
        sku_required=list_s,
        assigned_ws=None,
        arrival_time=sim.clock
        )
    sim.arrived_orders.push(o)
        
    ###  Scheduling next order arrival event
    e = Event(time= sim.clock+sim.ORDER_GEN_PARAMS[0], type= EventType.ARRIVAL_ORDER)
    sim.event_queue.push(e)


        



def run_optimizer(event, sim):
    pass

def release_task(event, sim):
    pass

def start_task(event, sim):
    pass

def arrival_pod_wst(event, sim):
    pass

def open_order(event, sim):
    pass

def start_picking(event, sim):
    pass

def end_picking(event, sim):
    pass

def close_order(event, sim):
    pass

def return_pod(event, sim):
    pass