# core/car_event_bus.py
# --------------------------------------------------
# Car / Wheel 이벤트를 event_id 기준으로 매칭하는 중앙 버스
#
# 핵심 정책
# - 순서 강제 ❌
# - event_id 매칭 100% 보장 ⭕
# - START 시 event_id 생성
# - car_no 확정 시 car_no → event_id 바인딩
# - wheel_status는 매핑 있으면 즉시 송신
#   매핑 없으면 pending에 보관했다가 나중에 송신
# --------------------------------------------------

import time
import threading
import uuid


class CarEventBus:
    def __init__(self, zmq_sender):
        """
        zmq_sender : ZmqSendWorker 인스턴스 (send(dict) 메서드 보유)
        """
        self.sender = zmq_sender
        self.lock = threading.Lock()

        # ★ 현재 진행 중인 세션 event_id
        self.current_event_id = None

        # ★ car_no -> event_id 매핑
        self.car_no_to_event = {}

        # ★ car_no 미확정 상태에서 들어온 wheel_status 임시 보관
        # 구조: { car_no(str) : [wheel_payload, ...] }
        self.pending_wheels = {}

    # --------------------------------------------------
    # 내부 유틸
    # --------------------------------------------------
    def _now_ms(self):
        return int(time.time() * 1000)

    def _new_event_id(self):
        # 가독성 있는 event_id
        return f"car-{self._now_ms()}-{uuid.uuid4().hex[:6]}"

    # --------------------------------------------------
    # START 이벤트
    # --------------------------------------------------
    def send_start(self):
        """
        대차 진입 감지 시 호출
        - event_id 생성
        - current_event_id 갱신
        - ZMQ START 송신
        """
        with self.lock:
            event_id = self._new_event_id()
            self.current_event_id = event_id

            payload = {
                "type": "car_event",
                "event": "START",
                "event_id": event_id,
                "ts_ms": self._now_ms(),
            }

            self.sender.send(payload)
            return event_id

    # --------------------------------------------------
    # 대차번호 확정
    # --------------------------------------------------
    def send_car_no(self, car_no):
        """
        대차번호 확정 시 호출
        - 현재 event_id에 car_no 바인딩
        - car_no 메시지 송신
        - pending wheel 이 있으면 즉시 매칭해서 송신
        """
        with self.lock:
            if self.current_event_id is None:
                # 비정상 케이스 방어
                return None

            event_id = self.current_event_id
            self.car_no_to_event[car_no] = event_id

            payload = {
                "type": "car_no",
                "event_id": event_id,
                "car_no": car_no,
                "ts_ms": self._now_ms(),
            }
            self.sender.send(payload)

            # ★ pending 되어 있던 wheel_status 처리
            if car_no in self.pending_wheels:
                for wheel_payload in self.pending_wheels[car_no]:
                    wheel_payload["event_id"] = event_id
                    wheel_payload["ts_ms"] = self._now_ms()
                    self.sender.send(wheel_payload)

                del self.pending_wheels[car_no]

            return event_id

    # --------------------------------------------------
    # 휠 상태 수신
    # --------------------------------------------------
    def on_wheel_status(self, wheel_payload):
        """
        wheel_flag_watcher 에서 호출
        wheel_payload 예:
        {
            "type": "wheel_status",
            "car_no": "090",
            "ws": {...},
            "ds": {...}
        }
        """
        with self.lock:
            car_no = wheel_payload.get("car_no")
            if not car_no:
                return

            # ★ 이미 car_no → event_id 매핑이 있으면 즉시 송신
            if car_no in self.car_no_to_event:
                event_id = self.car_no_to_event[car_no]
                wheel_payload["event_id"] = event_id
                wheel_payload["ts_ms"] = self._now_ms()
                self.sender.send(wheel_payload)
                return

            # ★ 아직 매핑이 없으면 pending
            if car_no not in self.pending_wheels:
                self.pending_wheels[car_no] = []

            # event_id 는 아직 붙이지 않음
            self.pending_wheels[car_no].append(wheel_payload)

    # --------------------------------------------------
    # END (선택적)
    # --------------------------------------------------
    def send_end(self):
        """
        세션 종료가 명확할 경우 호출
        (필수는 아님 – 구조상 START + car_no + wheel 만으로도 매칭 가능)
        """
        with self.lock:
            if self.current_event_id is None:
                return

            payload = {
                "type": "car_event",
                "event": "END",
                "event_id": self.current_event_id,
                "ts_ms": self._now_ms(),
            }
            self.sender.send(payload)

            self.current_event_id = None
