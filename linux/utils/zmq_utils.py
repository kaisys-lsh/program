# utils/zmq_utils.py
# --------------------------------------------------
# ZMQ 송신 워커 (thread-safe)
#  - ZeroMQ socket은 한 스레드에서만 사용해야 안전함
#  - 다른 스레드들은 Queue에 넣고, 워커가 send 수행
# --------------------------------------------------

import time
import json
import queue
import threading
import zmq

from config import config


class ZmqSendWorker:
    def __init__(self):
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.PUSH)

        # 송신 큐에 너무 많이 쌓이지 않도록
        self.sock.setsockopt(zmq.SNDHWM, 1)

        # 워커 큐
        self.q = queue.Queue(maxsize=1000)

        self.running = False
        self.thread = None

    def start(self):
        # bind는 워커가 소켓을 독점하는 스레드에서 하는 게 안전
        self.sock.bind(config.PUSH_BIND)
        print("[PUSH] bind", config.PUSH_BIND)

        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

        time.sleep(0.2)

    def _run(self):
        while self.running:
            try:
                item = self.q.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                # item은 str 또는 dict 허용
                if isinstance(item, dict):
                    msg = json.dumps(item, ensure_ascii=False)
                else:
                    msg = str(item)

                self.sock.send_string(msg)

            except Exception as e:
                print("[ZMQ] send error:", e)

    def send(self, item, block=False):
        """
        block=False 추천: 큐가 꽉 차면 그냥 드랍
        """
        try:
            self.q.put(item, block=block, timeout=0.01 if block else 0)
            return True
        except Exception:
            return False

    def close(self):
        self.running = False
        try:
            if self.thread is not None:
                self.thread.join(timeout=0.5)
        except:
            pass

        try:
            self.sock.close()
        except:
            pass

        try:
            self.ctx.term()
        except:
            pass
