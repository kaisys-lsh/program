# main_run.py
import time
import threading
from collections import defaultdict, deque

from config import config
from setup.detectron_setup import setup_detectron
from utils.zmq_utils import ZmqSendWorker
from mode.image_mode import run_image_mode
from mode.video_mode import run_video_mode
from utils.shared_mem_utils import open_or_create_shm, read_wheel_status_packet

TEST_IMAGE_MODE = True


class CarEventBus:
    """
    - car_event(START/END)와 wheel_event를 한 곳에서 관리
    - END 시 event_id 생성
    - wheel_event는 car_no 기준 FIFO 매칭
    """
    def __init__(self, sender):
        self.sender = sender
        self._seq = 0
        self._lock = threading.Lock()
        self._pending_by_car_no = defaultdict(deque)

    def _next_event_id(self):
        with self._lock:
            self._seq += 1
            seq = self._seq
        ms = int(time.time() * 1000)
        return f"car-{ms}-{seq}"

    def send_start(self):
        evt = {
            "type": "car_event",
            "event": "START",
            "ts_ms": int(time.time() * 1000),
        }
        self.sender.send(evt, block=False)
        print("[CAR] START")

    def send_end(self, car_no):
        event_id = self._next_event_id()
        evt = {
            "type": "car_event",
            "event": "END",
            "event_id": event_id,
            "car_no": str(car_no),
            "ts_ms": int(time.time() * 1000),
        }
        # wheel이 늦게 올 수 있으므로 pending 등록
        self._pending_by_car_no[str(car_no)].append(event_id)
        self.sender.send(evt, block=False)
        print("[CAR] END", evt)
        return event_id

    def on_wheel_event(self, pos_name, wheel_packet):
        wheel_car_no = str(wheel_packet.get("car_no", "")).strip()

        wheel_evt = {
            "type": "wheel_event",
            "pos": pos_name,   # "WS" or "DS"
            "wheel_car_no": wheel_car_no,
            "stop_flag": wheel_packet["stop_flag"],
            "wheel_1st_rotation": wheel_packet["wheel_1st_rotation"],
            "wheel_1st_position": wheel_packet["wheel_1st_position"],
            "wheel_2nd_rotation": wheel_packet["wheel_2nd_rotation"],
            "wheel_2nd_position": wheel_packet["wheel_2nd_position"],
            "ts_ms": int(time.time() * 1000),
        }

        matched_event_id = None
        q = self._pending_by_car_no.get(wheel_car_no)
        if q and len(q) > 0:
            matched_event_id = q.popleft()
            wheel_evt["event_id"] = matched_event_id

        self.sender.send(wheel_evt, block=False)
        print(f"[WHEEL-{pos_name}] {wheel_evt}")

        # 매칭 성공 시 HMI 편의용 업데이트 이벤트도 같이 보냄
        if matched_event_id is not None:
            update_evt = {
                "type": "car_update",
                "event_id": matched_event_id,
                "car_no": wheel_car_no,
                "pos": pos_name,
                "wheel": {
                    "stop_flag": wheel_packet["stop_flag"],
                    "wheel_1st_rotation": wheel_packet["wheel_1st_rotation"],
                    "wheel_1st_position": wheel_packet["wheel_1st_position"],
                    "wheel_2nd_rotation": wheel_packet["wheel_2nd_rotation"],
                    "wheel_2nd_position": wheel_packet["wheel_2nd_position"],
                },
                "ts_ms": int(time.time() * 1000),
            }
            self.sender.send(update_evt, block=False)
            print("[CAR-UPDATE]", update_evt)


# run_sender.py 안에서 WheelFlagWatcher 교체(핵심 부분만)

class WheelFlagWatcher(threading.Thread):
    def __init__(self, pos_name, status_array, car_bus, poll_interval=0.02):
        super().__init__(daemon=True)
        self.pos_name = pos_name
        self.status_array = status_array
        self.car_bus = car_bus
        self.poll_interval = poll_interval
        self.running = True
        self.pending = {}  # car_no -> {"stop":int, "ws1":(rot,pos), "ws2":(rot,pos)}

    def run(self):
        print(f"[WHEEL-WATCHER-{self.pos_name}] started")
        while self.running:
            try:
                arr = self.status_array
                if arr is None:
                    time.sleep(self.poll_interval)
                    continue

                # ---- 1st (flag 10) ----
                if int(arr[10]) == 1:
                    car_no = "".join(chr(int(arr[i])) for i in range(11, 14))
                    stop = int(arr[0])
                    r1 = int(arr[16])
                    p1 = int(arr[17])
                    arr[10] = 0  # 구조대로 Done

                    d = self.pending.get(car_no, {})
                    d["stop"] = stop
                    d["ws1"] = (r1, p1)
                    self.pending[car_no] = d

                # ---- 2nd (flag 20) ----
                if int(arr[20]) == 1:
                    car_no = "".join(chr(int(arr[i])) for i in range(21, 24))
                    stop = int(arr[0])
                    r2 = int(arr[26])
                    p2 = int(arr[27])
                    arr[20] = 0  # 구조대로 Done

                    d = self.pending.get(car_no, {})
                    d["stop"] = stop
                    d["ws2"] = (r2, p2)
                    self.pending[car_no] = d

                # ---- 둘 다 모이면 1회 전송 ----
                for car_no in list(self.pending.keys()):
                    d = self.pending[car_no]
                    if ("ws1" in d) and ("ws2" in d):
                        (r1, p1) = d["ws1"]
                        (r2, p2) = d["ws2"]
                        packet = {
                            "car_no": car_no,
                            "stop_flag": int(d.get("stop", 0)),
                            "wheel_1st_rotation": r1,
                            "wheel_1st_position": p1,
                            "wheel_2nd_rotation": r2,
                            "wheel_2nd_position": p2,
                        }
                        self.car_bus.on_wheel_event(self.pos_name, packet)
                        del self.pending[car_no]

                time.sleep(self.poll_interval)

            except Exception as e:
                print(f"[WHEEL-WATCHER-{self.pos_name}] error:", e)
                time.sleep(0.1)

    def stop(self):
        self.running = False



def main():
    predictor, metadata, mark_class_idx = setup_detectron()

    # ZMQ 송신 워커
    sender = ZmqSendWorker()
    sender.start()

    # 이벤트 버스
    car_bus = CarEventBus(sender)

    # 공유메모리 (WS / DS)
    shm_ws, shm_ws_buf = open_or_create_shm(config.SHM_WS_NAME, config.SHM_SIZE)
    print("[SHM] WS opened")

    shm_ds, shm_ds_buf = open_or_create_shm(config.SHM_DS_NAME, config.SHM_SIZE)
    print("[SHM] DS opened")

    # 휠 상태 watcher
    ws_watcher = WheelFlagWatcher("WS", shm_ws_buf, car_bus)
    ds_watcher = WheelFlagWatcher("DS", shm_ds_buf, car_bus)
    ws_watcher.start()
    ds_watcher.start()

    try:
        if TEST_IMAGE_MODE:
            print("[MAIN] IMAGE MODE")
            run_image_mode(
                predictor,
                metadata,
                mark_class_idx,
                car_bus,
                shm_ws_buf,
                shm_ds_buf,
            )
        else:
            print("[MAIN] VIDEO MODE")
            run_video_mode(
                predictor,
                metadata,
                mark_class_idx,
                car_bus,
                shm_ws_buf,
                shm_ds_buf,
            )
    finally:
        print("[MAIN] shutdown")
        try:
            ws_watcher.stop()
            ds_watcher.stop()
        except:
            pass
        try:
            sender.close()
        except:
            pass
        try:
            if shm_ws:
                shm_ws.close()
        except:
            pass
        try:
            if shm_ds:
                shm_ds.close()
        except:
            pass


if __name__ == "__main__":
    main()
