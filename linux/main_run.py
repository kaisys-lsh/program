# run_sender.py
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
    - car_event를 JSON으로 보내는 역할
    - END는 event_id를 만들어서 HMI가 안정적으로 매칭 가능하게 함
    - wheel_event는 wheel_car_no로 들어오므로,
      같은 번호가 중복될 때를 대비해 'FIFO 매칭'을 제공
    """
    def __init__(self, sender):
        self.sender = sender

        self._seq = 0
        self._lock = threading.Lock()

        # car_no -> deque[event_id]
        self._pending_by_car_no = defaultdict(deque)

    def _next_event_id(self):
        # 단순/안전: time + local seq
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
        ok = self.sender.send(evt, block=False)
        print(f"[CAR] START send_enq={ok} evt={evt}")

    def send_end(self, car_no):
        event_id = self._next_event_id()

        # END는 HMI 큐의 핵심 키가 되므로 먼저 보내는 게 중요
        evt = {
            "type": "car_event",
            "event": "END",
            "event_id": event_id,
            "car_no": str(car_no),
            "ts_ms": int(time.time() * 1000),
        }

        # wheel이 늦게 오므로 pending에 등록
        self._pending_by_car_no[str(car_no)].append(event_id)

        ok = self.sender.send(evt, block=False)
        print(f"[CAR] END send_enq={ok} evt={evt}")

        return event_id

    def on_wheel_event(self, pos_name, wheel_packet):
        """
        wheel_packet: read_wheel_status_packet() 결과
        - wheel_car_no로 pending에서 가장 오래된 event_id를 꺼내 매칭(FIFO)
        - wheel_event를 보내고,
        - 매칭되면 car_update(=완성 업데이트)도 같이 보냄
        """
        wheel_car_no = str(wheel_packet.get("car_no", "")).strip()

        # 기본 wheel_event (매칭 여부와 무관하게 일단 보냄)
        wheel_evt = {
            "type": "wheel_event",
            "pos": pos_name,
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

        ok1 = self.sender.send(wheel_evt, block=False)
        print(f"[WHEEL-{pos_name}] send_enq={ok1} evt={wheel_evt}")

        # ✅ 매칭 성공이면, HMI가 바로 업데이트하기 쉬운 car_update도 같이 보냄
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
            ok2 = self.sender.send(update_evt, block=False)
            print(f"[CAR-UPDATE] send_enq={ok2} evt={update_evt}")


class WheelFlagWatcher(threading.Thread):
    def __init__(self, pos_name, status_array, car_bus, poll_interval=0.02):
        super().__init__(daemon=True)
        self.pos_name = pos_name
        self.status_array = status_array
        self.car_bus = car_bus
        self.poll_interval = poll_interval
        self.running = True

    def run(self):
        print(f"[WHEEL-WATCHER-{self.pos_name}] started")
        while self.running:
            try:
                if self.status_array is not None and self.status_array[10] == 1:
                    packet = read_wheel_status_packet(self.status_array)

                    # 읽었으면 즉시 clear (다음 write 허용)
                    self.status_array[10] = 0

                    # 서버가 이벤트화해서 ZMQ로 송신
                    self.car_bus.on_wheel_event(self.pos_name, packet)

                time.sleep(self.poll_interval)
            except Exception as e:
                print(f"[WHEEL-WATCHER-{self.pos_name}] error:", e)
                time.sleep(0.1)

    def stop(self):
        self.running = False


def main():
    predictor, metadata, mark_class_idx = setup_detectron()

    # ✅ ZMQ 송신은 서버 하나 (워커)
    sender = ZmqSendWorker()
    sender.start()

    # ✅ car_event / wheel_event / update를 한 곳에서 관리
    car_bus = CarEventBus(sender)

    # 공유메모리 (WS/DS)
    shm_ws, shm_ws_buf = open_or_create_shm(config.SHM_WS_NAME, config.SHM_SIZE)
    print("[SHM] WS opened")

    shm_ds, shm_ds_buf = open_or_create_shm(config.SHM_DS_NAME, config.SHM_SIZE)
    print("[SHM] DS opened")

    # wheel flag watcher (WS/DS)
    ws_wheel_watcher = WheelFlagWatcher("WS", shm_ws_buf, car_bus)
    ds_wheel_watcher = WheelFlagWatcher("DS", shm_ds_buf, car_bus)
    ws_wheel_watcher.start()
    ds_wheel_watcher.start()

    try:
        if TEST_IMAGE_MODE:
            print("[MAIN] 이미지 모드 실행")
            run_image_mode(
                predictor,
                metadata,
                mark_class_idx,
                car_bus,
                shm_ws_buf,
                shm_ds_buf,
            )
        else:
            print("[MAIN] 영상 모드 실행")
            run_video_mode(
                predictor,
                metadata,
                mark_class_idx,
                car_bus,
                shm_ws_buf,
                shm_ds_buf,
            )

    finally:
        print("[MAIN] shutting down")

        try:
            ws_wheel_watcher.stop()
            ds_wheel_watcher.stop()
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
