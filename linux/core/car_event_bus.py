# core/car_event_bus.py
# --------------------------------------------------
# CarEventBus
# - car_event START/END 송신
# - END 때 event_id 생성
# - wheel_event(WS/DS)가 들어오면 같은 car_no의 "같은 사건(event_id)"에
#   WS/DS 둘 다 event_id를 붙여서 매칭되게 함
# --------------------------------------------------

import time
import threading
from collections import defaultdict, deque


class CarEventBus:
    def __init__(self, sender, pending_expire_sec=30.0):
        """
        sender: ZmqSendWorker 인스턴스
        pending_expire_sec: 너무 오래된 pending 사건 정리(초)
        """
        self.sender = sender

        self._seq = 0
        self._seq_lock = threading.Lock()

        # car_no -> deque([{"event_id":..., "need_ws":bool, "need_ds":bool, "ts_ms":int}, ...])
        self._pending_by_car_no = defaultdict(deque)

        # pending 접근은 여러 스레드(WS/DS watcher)에서 동시에 하므로 락 필요
        self._pending_lock = threading.Lock()

        self.pending_expire_sec = float(pending_expire_sec)

    # -----------------------------
    # 내부 유틸
    # -----------------------------
    def _now_ms(self):
        return int(time.time() * 1000)

    def _next_event_id(self):
        with self._seq_lock:
            self._seq += 1
            seq = self._seq

        ms = self._now_ms()
        return "car-" + str(ms) + "-" + str(seq)

    def _prune_old_locked(self, car_no, now_ms):
        """
        _pending_lock 잡힌 상태에서 호출해야 함
        """
        q = self._pending_by_car_no.get(car_no)
        if q is None:
            return

        expire_ms = int(self.pending_expire_sec * 1000)

        while len(q) > 0:
            head = q[0]
            ts_ms = int(head.get("ts_ms", now_ms))
            age = now_ms - ts_ms
            if age > expire_ms:
                q.popleft()
            else:
                break

        if len(q) == 0:
            try:
                del self._pending_by_car_no[car_no]
            except Exception:
                pass

    def _match_event_id_locked(self, car_no, pos_name, now_ms):
        """
        _pending_lock 잡힌 상태에서 호출해야 함.
        pos_name: "WS" or "DS"
        return: matched_event_id or None
        """
        self._prune_old_locked(car_no, now_ms)

        q = self._pending_by_car_no.get(car_no)
        if q is None or len(q) == 0:
            return None

        need_key = "need_ws" if pos_name == "WS" else "need_ds"

        # 가장 오래된 사건부터 "이 pos가 아직 필요"한 것을 찾는다
        i = 0
        while i < len(q):
            rec = q[i]
            if bool(rec.get(need_key, False)):
                event_id = rec.get("event_id")

                # 이 pos는 매칭 완료
                rec[need_key] = False

                # WS/DS 둘 다 채워지면 사건 제거
                if (not bool(rec.get("need_ws", False))) and (not bool(rec.get("need_ds", False))):
                    try:
                        q.remove(rec)
                    except Exception:
                        # remove가 실패해도 크게 문제는 없지만, 남아있으면 중복매칭 위험
                        # 안전하게 앞에서부터 prune 성격으로 정리 시도
                        pass

                # 빈 큐면 dict 정리
                if len(q) == 0:
                    try:
                        del self._pending_by_car_no[car_no]
                    except Exception:
                        pass

                return event_id

            i += 1

        return None

    # -----------------------------
    # 외부 API
    # -----------------------------
    def send_start(self):
        evt = {
            "type": "car_event",
            "event": "START",
            "ts_ms": self._now_ms(),
        }
        self.sender.send(evt, block=False)
        print("[CAR] START")

    def send_end(self, car_no):
        """
        car_no: "060" 같은 3자리 문자열(또는 비슷한 값)
        """
        car_no = str(car_no).strip()
        now_ms = self._now_ms()

        event_id = self._next_event_id()

        with self._pending_lock:
            self._prune_old_locked(car_no, now_ms)

            rec = {
                "event_id": event_id,
                "need_ws": True,
                "need_ds": True,
                "ts_ms": now_ms,
            }
            self._pending_by_car_no[car_no].append(rec)

        evt = {
            "type": "car_event",
            "event": "END",
            "event_id": event_id,
            "car_no": car_no,
            "ts_ms": now_ms,
        }
        self.sender.send(evt, block=False)
        print("[CAR] END", evt)
        return event_id

    def on_wheel_event(self, pos_name, wheel_packet):
        """
        pos_name: "WS" or "DS"
        wheel_packet: {
            "car_no": "060",
            "stop_flag": int,
            "wheel_1st_rotation": int,
            "wheel_1st_position": int,
            "wheel_2nd_rotation": int,
            "wheel_2nd_position": int,
        }
        """
        pos_name = str(pos_name).strip().upper()
        wheel_car_no = str(wheel_packet.get("car_no", "")).strip()
        now_ms = self._now_ms()

        wheel_evt = {
            "type": "wheel_event",
            "pos": pos_name,
            "wheel_car_no": wheel_car_no,
            "stop_flag": int(wheel_packet.get("stop_flag", 0)),
            "wheel_1st_rotation": int(wheel_packet.get("wheel_1st_rotation", 0)),
            "wheel_1st_position": int(wheel_packet.get("wheel_1st_position", 0)),
            "wheel_2nd_rotation": int(wheel_packet.get("wheel_2nd_rotation", 0)),
            "wheel_2nd_position": int(wheel_packet.get("wheel_2nd_position", 0)),
            "ts_ms": now_ms,
        }

        matched_event_id = None
        with self._pending_lock:
            matched_event_id = self._match_event_id_locked(wheel_car_no, pos_name, now_ms)

        if matched_event_id is not None:
            wheel_evt["event_id"] = matched_event_id

        self.sender.send(wheel_evt, block=False)
        #print("[WHEEL-" + pos_name + "]", wheel_evt)

        # 매칭 성공 시 HMI 편의용 업데이트 이벤트도 같이 보냄
        if matched_event_id is not None:
            update_evt = {
                "type": "car_update",
                "event_id": matched_event_id,
                "car_no": wheel_car_no,
                "pos": pos_name,
                "wheel": {
                    "stop_flag": int(wheel_packet.get("stop_flag", 0)),
                    "wheel_1st_rotation": int(wheel_packet.get("wheel_1st_rotation", 0)),
                    "wheel_1st_position": int(wheel_packet.get("wheel_1st_position", 0)),
                    "wheel_2nd_rotation": int(wheel_packet.get("wheel_2nd_rotation", 0)),
                    "wheel_2nd_position": int(wheel_packet.get("wheel_2nd_position", 0)),
                },
                "ts_ms": now_ms,
            }
            self.sender.send(update_evt, block=False)
            #print("[CAR-UPDATE]", update_evt)
