# zmq_utils.py
# --------------------------------------------------
# ZMQ 송신 소켓 생성
# --------------------------------------------------

import time
import zmq

from config import config 


def make_zmq_sender():
    """
    ZMQ PUSH 소켓을 생성하고 bind 한 뒤 (ctx, socket)을 반환.
    """
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.PUSH)

    # 송신 큐에 너무 많이 쌓이지 않도록
    sock.setsockopt(zmq.SNDHWM, 1)

    sock.bind(config.PUSH_BIND)
    print("[PUSH] bind", config.PUSH_BIND)

    time.sleep(0.5)
    return ctx, sock
