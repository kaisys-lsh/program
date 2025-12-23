# core/wheel_flag_watcher.py
# --------------------------------------------------
# WheelFlagWatcher
# - 공유메모리 구조(문서) 그대로 감시
#   DS: flag 10(1st), 20(2nd)
#   WS: flag 30(1st), 40(2nd)
# - flag==1 이면 읽고 flag=0으로 내림(Done)
# - 기본 동작: 1st/2nd 둘 다 모이면 "1회" car_bus.on_wheel_event() 호출
#   (필요하면 send_when_both=False 로 1st/2nd 각각 전송도 가능)
# --------------------------------------------------

import time
import threading


class WheelFlagWatcher(threading.Thread):
    def __init__(
        self,
        pos_name,
        status_array,
        car_bus,
        poll_interval=0.02,
        send_when_both=True,
    ):
        super().__init__(daemon=True)

        self.pos_name = str(pos_name).strip().upper()  # "WS" or "DS"
        self.status_array = status_array
        self.car_bus = car_bus
        self.poll_interval = float(poll_interval)
        self.send_when_both = bool(send_when_both)

        self.running = True

        # car_no -> {"stop":int, "w1":(rot,pos), "w2":(rot,pos)}
        self.pending = {}

        # ✅ 인덱스 매핑 (문서 그대로)
        if self.pos_name == "DS":
            self.flag1 = 10
            self.car1 = (11, 12, 13)
            self.rot1 = 16
            self.pos1 = 17

            self.flag2 = 20
            self.car2 = (21, 22, 23)
            self.rot2 = 26
            self.pos2 = 27

        else:  # "WS"
            self.flag1 = 30
            self.car1 = (31, 32, 33)
            self.rot1 = 36
            self.pos1 = 37

            self.flag2 = 40
            self.car2 = (41, 42, 43)
            self.rot2 = 46
            self.pos2 = 47

    # -----------------------------
    # 내부 유틸
    # -----------------------------
    def _read_ascii3(self, arr, idxs):
        # 3바이트를 ASCII로 읽어 문자열로 반환
        # (0값 등 이상치가 있으면 'F'로 치환해서 3자리 유지)
        out = []
        k = 0
        while k < 3:
            v = int(arr[idxs[k]])
            ch = chr(v) if 0 <= v <= 255 else "F"
            if ch.isdigit() or ch.upper() == "F":
                out.append(ch.upper())
            else:
                out.append("F")
            k += 1
        return "".join(out)

    def _send_packet(self, car_no, stop, r1, p1, r2, p2):
        packet = {
            "car_no": car_no,
            "stop_flag": int(stop),
            "wheel_1st_rotation": int(r1),
            "wheel_1st_position": int(p1),
            "wheel_2nd_rotation": int(r2),
            "wheel_2nd_position": int(p2),
        }
        self.car_bus.on_wheel_event(self.pos_name, packet)

    # -----------------------------
    # Thread main
    # -----------------------------
    def run(self):
        print("[WHEEL-WATCHER-" + self.pos_name + "] started")

        while self.running:
            try:
                arr = self.status_array
                if arr is None:
                    time.sleep(self.poll_interval)
                    continue

                stop = int(arr[0])  # 0: 이동 / 1: 정지

                # ---- 1st ----
                if int(arr[self.flag1]) == 1:
                    car_no = self._read_ascii3(arr, self.car1)
                    r1 = int(arr[self.rot1])
                    p1 = int(arr[self.pos1])

                    # ✅ 읽었으면 반드시 Done
                    arr[self.flag1] = 0

                    if self.send_when_both:
                        d = self.pending.get(car_no, {})
                        d["stop"] = stop
                        d["w1"] = (r1, p1)
                        self.pending[car_no] = d
                    else:
                        # 1st만 들어온 경우라도 즉시 전송
                        self._send_packet(car_no, stop, r1, p1, 0, 0)

                # ---- 2nd ----
                if int(arr[self.flag2]) == 1:
                    car_no = self._read_ascii3(arr, self.car2)
                    r2 = int(arr[self.rot2])
                    p2 = int(arr[self.pos2])

                    # ✅ 읽었으면 반드시 Done
                    arr[self.flag2] = 0

                    if self.send_when_both:
                        d = self.pending.get(car_no, {})
                        d["stop"] = stop
                        d["w2"] = (r2, p2)
                        self.pending[car_no] = d
                    else:
                        # 2nd만 들어온 경우라도 즉시 전송
                        self._send_packet(car_no, stop, 0, 0, r2, p2)

                # ---- (기본) 둘 다 모이면 1회 전송 ----
                if self.send_when_both:
                    for car_no in list(self.pending.keys()):
                        d = self.pending.get(car_no)
                        if d is None:
                            continue

                        if ("w1" in d) and ("w2" in d):
                            r1, p1 = d["w1"]
                            r2, p2 = d["w2"]
                            st = int(d.get("stop", 0))

                            self._send_packet(car_no, st, r1, p1, r2, p2)

                            # 전송 완료
                            try:
                                del self.pending[car_no]
                            except Exception:
                                pass

                time.sleep(self.poll_interval)

            except Exception as e:
                print("[WHEEL-WATCHER-" + self.pos_name + "] error:", e)
                time.sleep(0.1)

    def stop(self):
        self.running = False
