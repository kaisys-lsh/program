# -*- coding: utf-8 -*-
import json
import time
import zmq

PUSH_BIND = "tcp://192.168.0.103:5577"

def _pretty_print(raw):
    # raw: str
    try:
        obj = json.loads(raw)
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    except Exception:
        # JSON이 아니면 그냥 원문 출력
        print(raw)


def main():
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.PULL)

    # 서버가 bind(PUSH_BIND) 한 주소로 connect
    sock.connect(PUSH_BIND)
    print("[PULL] connect",PUSH_BIND)

    # 폴링으로 깔끔하게 받기 (Ctrl+C 종료)
    poller = zmq.Poller()
    poller.register(sock, zmq.POLLIN)

    print("---- recv start (Ctrl+C to stop) ----")
    while True:
        events = dict(poller.poll(timeout=1000))
        if sock in events and events[sock] == zmq.POLLIN:
            raw = sock.recv_string()
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            print("\n==============================")
            print("[RECV]", ts)
            _pretty_print(raw)


if __name__ == "__main__":
    main()
