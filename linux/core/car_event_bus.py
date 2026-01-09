# linux/core/car_event_bus.py
# --------------------------------------------------
# [수정] CarEventBus가 상태 머신(Start/End 판단)을 통합 관리함
# - 5프레임 연속 검출 시 START
# - 5프레임 연속 미검출 시 END
# --------------------------------------------------

import time
import threading
import uuid

from config import config
from utils.shared_mem_utils import write_car_number

class CarEventBus:
    def __init__(self, zmq_sender, debug_print=False):
        self.sender = zmq_sender
        self.debug_print = bool(debug_print)
        self.lock = threading.Lock()

        # ------------------------------------------------
        # [통합] 상태 머신 변수들
        # ------------------------------------------------
        self.in_wagon = False
        
        # [추가] 시작 판단용 변수 (연속 검출 카운트)
        self.digit_on_frames = 0
        self.start_threshold = int(getattr(config, "DIGIT_START_FRAMES", 5))

        # [수정] 종료 판단용 변수 (연속 미검출 카운트)
        self.no_digit_frames = 0
        self.max_no_digit = int(getattr(config, "NO_DIGIT_END_FRAMES", 5))
        
        self.session_best_code = "FFF"
        
        # 기존 변수들
        self.current_event_id = None
        self.car_no_to_event = {}
        self.pending_wheels = {}

        self.max_pending_per_car = int(getattr(config, "CARBUS_MAX_PENDING_PER_CAR", 20))
        self.max_map_size = int(getattr(config, "CARBUS_MAX_MAP_SIZE", 200))
        self.send_end_event = bool(getattr(config, "CARBUS_SEND_END_EVENT", False))

    def _now_ms(self):
        return int(time.time() * 1000)

    def _make_event_id(self):
        return "car-{0}-{1}".format(self._now_ms(), uuid.uuid4().hex[:6])

    def _normalize_car_no_3(self, s):
        if s is None: return "FFF"
        t = str(s).strip()
        if t == "" or t.upper() == "NONE": return "FFF"
        digits = "".join([ch for ch in t if ch.isdigit()])
        if len(digits) != 3: return "FFF"
        return digits

    # ---------------------------
    # [핵심] 상태 업데이트 (Main에서 호출)
    # ---------------------------
    def update_wagon_status(self, has_digit, frame_code, shm_array=None):
        """
        Main loop에서 매 프레임 호출.
        - has_digit: 현재 프레임에 숫자가 있는가? (True/False)
        - frame_code: 현재 프레임에서 조합된 번호 (없으면 "FFF")
        - shm_array: 종료 시 번호를 쓸 공유메모리 배열
        """
        with self.lock:
            if has_digit:
                # [숫자 감지됨]
                self.no_digit_frames = 0        # 종료 카운터 리셋
                self.digit_on_frames += 1       # 시작 카운터 증가

                # 1) 이미 진입한 상태라면 -> 번호 갱신만 수행
                if self.in_wagon:
                    if frame_code and frame_code != "FFF":
                        self.session_best_code = frame_code

                # 2) 아직 진입 전이라면 -> 연속 프레임 체크 후 START
                else:
                    if self.digit_on_frames >= self.start_threshold:
                        self._start_session()
                        # START 직후 현재 프레임의 번호도 반영
                        if frame_code and frame_code != "FFF":
                            self.session_best_code = frame_code

            else:
                # [숫자 없음]
                self.digit_on_frames = 0        # 연속 검출 실패 -> 시작 카운터 리셋

                if self.in_wagon:
                    self.no_digit_frames += 1
                    # 5프레임(설정값) 이상 안 보이면 -> END
                    if self.no_digit_frames >= self.max_no_digit:
                        self._end_session(shm_array)

    def _start_session(self):
        """내부 호출용: 세션 시작"""
        self.in_wagon = True
        self.session_best_code = "FFF"
        self.no_digit_frames = 0
        # self.digit_on_frames는 초기화하지 않음 (update_wagon_status에서 관리)
        
        # 기존 send_start 로직
        if self.current_event_id is not None:
            return 

        self.current_event_id = self._make_event_id()
        self._send({
            "type": "car_event",
            "event": "START",
            "car_no": None,
            "event_id": self.current_event_id,
            "ts_ms": self._now_ms(),
        })
        if self.debug_print:
            print(f"[BUS] AUTO START (ID: {self.current_event_id})")

    def _end_session(self, shm_array):
        """내부 호출용: 세션 종료 및 확정"""
        final_code = self.session_best_code
        if self.debug_print:
            print(f"[BUS] AUTO END -> Final Code: {final_code}")

        # 1. ZMQ 전송 (CAR_NO)
        self._internal_send_car_no(final_code)

        # 2. SHM 쓰기
        if shm_array is not None:
            # block=True로 휠 프로그램 동기화 대기
            ok = write_car_number(shm_array, final_code, block=True, timeout_sec=1.0)
            if not ok and self.debug_print:
                print(f"[BUS-WARN] SHM write timeout for {final_code}")

        # 3. 상태 초기화
        self.in_wagon = False
        self.session_best_code = "FFF"
        self.no_digit_frames = 0
        self.digit_on_frames = 0    # 시작 카운터도 확실히 초기화
        self.current_event_id = None

    def _internal_send_car_no(self, car_no_str):
        car_no = self._normalize_car_no_3(car_no_str)
        if self.current_event_id is None:
            self.current_event_id = self._make_event_id()
        
        event_id = self.current_event_id
        self.car_no_to_event[car_no] = event_id
        self._trim_map_if_needed()

        self._send({
            "type": "car_no",
            "event_id": event_id,
            "car_no": car_no,
            "ts_ms": self._now_ms(),
        })

        if self.send_end_event:
            self._send({
                "type": "car_event",
                "event": "END",
                "car_no": car_no,
                "event_id": event_id,
                "ts_ms": self._now_ms(),
            })

        self._flush_pending_wheels_locked(car_no, event_id)

    # ---------------------------
    # 기존 유틸 메서드 (유지)
    # ---------------------------
    def _trim_map_if_needed(self):
        if len(self.car_no_to_event) <= self.max_map_size: return
        keys = list(self.car_no_to_event.keys())
        cut = len(keys) - self.max_map_size
        for i in range(cut):
            self.car_no_to_event.pop(keys[i], None)

    def _trim_pending_if_needed(self, car_no):
        lst = self.pending_wheels.get(car_no, None)
        if lst and len(lst) > self.max_pending_per_car:
            self.pending_wheels[car_no] = lst[-self.max_pending_per_car:]

    def _send(self, payload):
        if self.debug_print: print("[BUS] SEND:", payload)
        if self.sender: self.sender.send(payload)

    def on_wheel_status(self, wheel_payload):
        if wheel_payload is None: return
        car_no = self._normalize_car_no_3(wheel_payload.get("car_no", None))

        with self.lock:
            if car_no in self.car_no_to_event:
                wheel_payload["event_id"] = self.car_no_to_event[car_no]
                wheel_payload["ts_ms"] = self._now_ms()
                self._send(wheel_payload)
            else:
                if car_no not in self.pending_wheels:
                    self.pending_wheels[car_no] = []
                self.pending_wheels[car_no].append(wheel_payload)
                self._trim_pending_if_needed(car_no)
                if self.debug_print:
                    print(f"[BUS] wheel pending: {car_no} count={len(self.pending_wheels[car_no])}")

    def _flush_pending_wheels_locked(self, car_no, event_id):
        lst = self.pending_wheels.pop(car_no, None)
        if not lst: return
        if self.debug_print:
            print(f"[BUS] flush pending: {car_no} count={len(lst)}")
        for p in lst:
            p["event_id"] = event_id
            p["ts_ms"] = self._now_ms()
            self._send(p)