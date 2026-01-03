# utils/zmq_utils.py
# --------------------------------------------------
# ZMQ 송신 워커
# [수정] Queue 사이즈 1 -> 1000 (데이터 유실 방지)
# --------------------------------------------------

import queue
import threading
import time
import uuid
import zmq
from zmq.utils.monitor import recv_monitor_message
from config import config

class ZmqSendWorker:
    def __init__(self, bind_addr=None, debug_print=False):
        self.bind_addr = str(config.PUSH_BIND if bind_addr is None else bind_addr)
        self.debug_print = bool(debug_print)

        # [수정] 큐 크기 대폭 증가 (1 -> 1000)
        # 동시에 여러 이벤트가 발생해도 유실되지 않음
        self.q = queue.Queue(maxsize=1000)

        self.running = False
        self.thread = None
        self.ctx = None
        self.sock = None

        self.mon_sock = None
        self.mon_thread = None
        self.peer_count = 0
        self.has_peer = False

        self.sending_active = False
        self.lock = threading.Lock()
        self.cached_last = None

    def start(self):
        if self.running:
            return

        self.running = True
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.PUSH)

        try:
            self.sock.setsockopt(zmq.IMMEDIATE, 1)
        except Exception:
            pass
        try:
            self.sock.setsockopt(zmq.SNDHWM, int(getattr(config, "ZMQ_SNDHWM", 1)))
        except Exception:
            pass

        self.sock.bind(self.bind_addr)

        mon_addr = "inproc://zmq-monitor-{0}".format(uuid.uuid4().hex)
        try:
            self.sock.monitor(mon_addr, zmq.EVENT_ACCEPTED | zmq.EVENT_DISCONNECTED)
            self.mon_sock = self.ctx.socket(zmq.PAIR)
            self.mon_sock.connect(mon_addr)
            self.mon_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.mon_thread.start()
        except Exception as e:
            if self.debug_print:
                print("[ZMQ] monitor setup failed:", e)
            self.mon_sock = None
            self.mon_thread = None

        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

        if self.debug_print:
            print("[ZMQ] sender started:", self.bind_addr)

    def close(self):
        if not self.running:
            return
        self.running = False
        try:
            self.q.put_nowait(None)
        except Exception:
            pass
        try:
            if self.thread is not None:
                self.thread.join(timeout=0.5)
        except Exception:
            pass
        try:
            if self.mon_thread is not None:
                self.mon_thread.join(timeout=0.5)
        except Exception:
            pass
        try:
            if self.mon_sock is not None:
                self.mon_sock.close(0)
        except Exception:
            pass
        try:
            if self.sock is not None:
                try:
                    self.sock.disable_monitor()
                except Exception:
                    pass
                self.sock.close(0)
        except Exception:
            pass
        self.sock = None
        self.ctx = None
        self.thread = None
        self.mon_sock = None
        self.mon_thread = None
        if self.debug_print:
            print("[ZMQ] sender closed")

    def stop(self):
        self.close()

    def send(self, payload, block=False):
        if not self.running:
            return False

        is_start = False
        if isinstance(payload, dict):
            if payload.get("type") == "car_event" and payload.get("event") == "START":
                is_start = True

        if not self.has_peer:
            with self.lock:
                self.cached_last = payload
            return True

        if not self.sending_active:
            if not is_start:
                with self.lock:
                    self.cached_last = payload
                return True
            self.sending_active = True

        # [수정] 큐가 꽉 차있으면(거의 없겠지만) 비우고 넣기
        if not block:
            while self.q.full():
                try:
                    self.q.get_nowait()
                except Exception:
                    break
            try:
                self.q.put_nowait(payload)
                return True
            except Exception:
                return False

        try:
            self.q.put(payload, timeout=float(getattr(config, "ZMQ_QUEUE_PUT_TIMEOUT_SEC", 0.01)))
            return True
        except Exception:
            return False

    def _monitor_loop(self):
        while self.running and self.mon_sock is not None:
            try:
                evt = recv_monitor_message(self.mon_sock, flags=0)
            except Exception:
                time.sleep(0.05)
                continue
            ev = int(evt.get("event", 0))

            if ev == zmq.EVENT_ACCEPTED:
                self.peer_count += 1
                if self.peer_count < 0: self.peer_count = 0
                if self.peer_count > 0:
                    self.has_peer = True
                    if self.debug_print: print("[ZMQ] peer connected (wait START)")

            elif ev == zmq.EVENT_DISCONNECTED:
                self.peer_count -= 1
                if self.peer_count < 0: self.peer_count = 0
                if self.peer_count == 0:
                    self.has_peer = False
                    self.sending_active = False
                    # Disconnect 시 큐 초기화
                    while self.q.full():
                        try: self.q.get_nowait()
                        except Exception: break
                    if self.debug_print: print("[ZMQ] peer disconnected -> wait START")

    def _loop(self):
        while self.running:
            try:
                item = self.q.get(timeout=0.1)
            except queue.Empty:
                continue
            except Exception:
                continue

            if item is None:
                continue

            if (not self.has_peer) or (not self.sending_active):
                with self.lock:
                    self.cached_last = item
                continue

            try:
                if isinstance(item, dict):
                    self.sock.send_json(item, ensure_ascii=False)
                elif isinstance(item, (bytes, bytearray)):
                    self.sock.send(bytes(item))
                else:
                    self.sock.send_string(str(item))

                if self.debug_print and isinstance(item, dict):
                    print("[ZMQ] sent:", item.get("type"))

            except Exception as e:
                if self.debug_print:
                    print("[ZMQ] send error:", e)
                time.sleep(0.02)