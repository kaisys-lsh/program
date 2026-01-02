# core/wheel_flag_watcher.py
# --------------------------------------------------
# WheelFlagWatcher (단순화 버전)
# - SHM 폴링해서 WS/DS 1st/2nd flag 감시
# - flag==1이면 즉시 읽고 즉시 전송 (대기 없음)
# --------------------------------------------------

import time
import threading
from config import config

def _now_ms():
    return int(time.time() * 1000)

def _read_carno3(arr, idx3):
    s = ""
    i = 0
    while i < 3:
        v = int(arr[idx3[i]])
        ch = "F"
        try:
            c = chr(v)
            if c.isdigit():
                ch = c
        except Exception:
            ch = "F"
        s += ch
        i += 1
    return s

class WheelFlagWatcher(threading.Thread):
    def __init__(
        self,
        pos_name,            # "WS" or "DS"
        shm_array,           # np.ndarray(uint8)
        car_bus,             # CarEventBus
        poll_interval=None,
        clear_flag_on_read=True,
        debug_print=False
    ):
        threading.Thread.__init__(self, daemon=True)

        self.pos = str(pos_name).upper().strip()
        self.arr = shm_array
        self.bus = car_bus

        self.poll_interval = float(
            config.WHEEL_POLL_INTERVAL_SEC if poll_interval is None else poll_interval
        )
        self.clear_flag_on_read = bool(clear_flag_on_read)
        self.debug_print = bool(debug_print)

        # pos별 인덱스 매핑
        self._map_indices()
        self.running = True

    def _map_indices(self):
        if self.pos == "DS":
            self.flag1 = config.DS_FLAG_1
            self.car1 = config.DS_CAR_1
            self.rot1 = config.DS_ROT_1
            self.pos1 = config.DS_POS_1

            self.flag2 = config.DS_FLAG_2
            self.car2 = config.DS_CAR_2
            self.rot2 = config.DS_ROT_2
            self.pos2 = config.DS_POS_2
            return

        # default: WS
        self.flag1 = config.WS_FLAG_1
        self.car1 = config.WS_CAR_1
        self.rot1 = config.WS_ROT_1
        self.pos1 = config.WS_POS_1

        self.flag2 = config.WS_FLAG_2
        self.car2 = config.WS_CAR_2
        self.rot2 = config.WS_ROT_2
        self.pos2 = config.WS_POS_2

    def _emit(self, payload):
        if self.debug_print:
            print("[WHEEL-" + self.pos + "] SEND:", payload)

        if self.bus is None:
            return

        if hasattr(self.bus, "on_wheel_status"):
            self.bus.on_wheel_status(payload)

    def _make_payload(self, car_no, stop_flag, w1, w2, src):
        return {
            "type": "wheel_status",
            "pos": self.pos,
            "car_no": car_no,
            "stop_flag": int(stop_flag),
            "wheel1_rotation": int(w1[0]),
            "wheel1_position": int(w1[1]),
            "wheel2_rotation": int(w2[0]),
            "wheel2_position": int(w2[1]),
            "src": str(src),
            "ts_ms": _now_ms(),
        }

    def run(self):
        while self.running:
            try:
                stop_flag = int(self.arr[config.IDX_STOP_FLAG])

                # 1st Wheel Check
                if int(self.arr[self.flag1]) == 1:
                    car_no = _read_carno3(self.arr, self.car1)
                    rot = int(self.arr[self.rot1])
                    pos = int(self.arr[self.pos1])

                    if self.clear_flag_on_read:
                        self.arr[self.flag1] = 0

                    if self.debug_print:
                        print(f"[WHEEL-{self.pos}] RECV 1st: {car_no}, rot={rot}, pos={pos}")

                    # [수정] 대기 없이 즉시 전송
                    payload = self._make_payload(car_no, stop_flag, (rot, pos), (0, 0), "1st")
                    self._emit(payload)

                # 2nd Wheel Check
                if int(self.arr[self.flag2]) == 1:
                    car_no = _read_carno3(self.arr, self.car2)
                    rot = int(self.arr[self.rot2])
                    pos = int(self.arr[self.pos2])

                    if self.clear_flag_on_read:
                        self.arr[self.flag2] = 0

                    if self.debug_print:
                        print(f"[WHEEL-{self.pos}] RECV 2nd: {car_no}, rot={rot}, pos={pos}")

                    # [수정] 대기 없이 즉시 전송
                    payload = self._make_payload(car_no, stop_flag, (0, 0), (rot, pos), "2nd")
                    self._emit(payload)

                time.sleep(self.poll_interval)

            except Exception as e:
                print(f"[WHEEL-WATCHER-{self.pos}] error: {e}")
                time.sleep(0.1)

    def stop(self):
        self.running = False