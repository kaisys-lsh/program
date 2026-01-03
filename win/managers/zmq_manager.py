# win/managers/zmq_manager.py
# -*- coding: utf-8 -*-
import json
import time
import zmq
from PyQt5.QtCore import QThread, pyqtSignal, QObject

from config.config import PULL_CONNECT1
from utils.wheel_status_utils import judge_one_wheel
from workers.db_worker import DbWriterThread, DbPollerThread

# ==================================================
# 1. ZMQ 수신 스레드 (내부 클래스로 통합)
# ==================================================
class ZmqRecvThread(QThread):
    text_ready = pyqtSignal(str)

    def __init__(self, addr):
        super().__init__()
        self.addr = addr
        self._running = True
        self.ctx = None
        self.sock = None

    def run(self):
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.PULL)
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.setsockopt(zmq.RCVHWM, 200)
        self.sock.connect(self.addr)

        while self._running:
            try:
                # 타임아웃 없이 블로킹 대기하되, 일정 주기로 running 체크 권장
                # 여기서는 간단히 Polling 방식으로 구현
                if self.sock.poll(500) == 0:
                    continue
                
                msg_bytes = self.sock.recv()
                msg = msg_bytes.decode("utf-8", errors="ignore").strip()
                if not msg:
                    continue
                
                # \n으로 구분된 JSON 처리
                if "\n" in msg:
                    for line in msg.splitlines():
                        if line.strip():
                            self.text_ready.emit(line.strip())
                else:
                    self.text_ready.emit(msg)

            except Exception as e:
                print(f"[ZMQ] Error: {e}")
                time.sleep(1)

        self.sock.close()
        self.ctx.term()

    def stop(self):
        self._running = False
        self.wait()


# ==================================================
# 2. ZMQ 매니저 (로직 통합)
# ==================================================
class ZmqManager(QObject):
    """
    ZMQ 메시지 수신 -> 파싱 -> 로직 처리 -> Controller/UI 전달
    """
    # UI 업데이트용 시그널
    sig_update_wheel_ui = pyqtSignal(str, str, str)  # pos(WS/DS), status1, status2
    sig_clear_ui = pyqtSignal()

    def __init__(self, wagon_ctrl, db_writer):
        super().__init__()
        self.wagon_ctrl = wagon_ctrl
        self.db_writer = db_writer
        
        # 현재 처리 중인 이벤트 ID (UI 필터링용)
        self.current_event_id = None

        # 스레드 시작
        self.thread = ZmqRecvThread(PULL_CONNECT1)
        self.thread.text_ready.connect(self._process_message)
        
    def start(self):
        self.thread.start()

    def stop(self):
        self.thread.stop()

    def _process_message(self, text):
        """MainRun에 있던 복잡한 파싱 로직을 여기로 이동"""
        try:
            data = json.loads(text)
        except Exception:
            return

        mtype = str(data.get("type", "")).strip().lower()
        event_id = str(data.get("event_id", "") or "").strip()

        # ----------------------------------
        # A. 차량 이벤트 (START / END)
        # ----------------------------------
        if mtype == "car_event":
            ev = str(data.get("event", "")).strip().upper()
            
            if ev == "START" and event_id:
                self.current_event_id = event_id
                self.sig_clear_ui.emit()  # UI 초기화 신호
            
            if ev == "END" and event_id == self.current_event_id:
                self.current_event_id = None

            # Controller에게 알림
            self.wagon_ctrl.on_car_event(data)
            return

        # ----------------------------------
        # B. 차량 번호 (END 대체 로직 포함)
        # ----------------------------------
        if mtype == "car_no":
            self.wagon_ctrl.on_car_no(data)
            
            # (요구사항) car_no를 받으면 해당 이벤트를 END로 간주
            if event_id and event_id == self.current_event_id:
                self.current_event_id = None
                # 강제 END 이벤트 주입 (Controller 내부 상태 정리용)
                self.wagon_ctrl.on_car_event({"event": "END", "event_id": event_id})
            return

        # ----------------------------------
        # C. 휠 상태 / 업데이트
        # ----------------------------------
        if mtype in ("wheel_status", "wheel_event", "car_update"):
            self._handle_wheel_logic(data, event_id)
            return

    def _handle_wheel_logic(self, data, event_id):
        """MainRun에 있던 _handle_wheel_like_event 로직"""
        pos = str(data.get("pos", "")).strip().upper()
        if not pos:
            return

        # 1. 휠 상태 판정
        # (데이터 포맷 호환성 유지)
        wheel = data.get("wheel", {})
        if wheel:
            w1 = (wheel.get("wheel_1st_rotation", 0), wheel.get("wheel_1st_position", 0))
            w2 = (wheel.get("wheel_2nd_rotation", 0), wheel.get("wheel_2nd_position", 0))
        else:
            w1 = (data.get("wheel_1st_rotation", 0), data.get("wheel_1st_position", 0))
            w2 = (data.get("wheel_2nd_rotation", 0), data.get("wheel_2nd_position", 0))

        s1 = judge_one_wheel(w1)
        s2 = judge_one_wheel(w2)

        # 2. DB 저장 (Patch Enqueue)
        if event_id:
            patch = {"event_id": event_id}
            if pos == "WS":
                patch.update({"ws_wheel1_status": s1, "ws_wheel2_status": s2, "wheel_ws_done": 1})
            elif pos == "DS":
                patch.update({"ds_wheel1_status": s1, "ds_wheel2_status": s2, "wheel_ds_done": 1})
            
            try:
                self.db_writer.enqueue(patch)
            except Exception:
                pass

        # 3. UI 업데이트 신호 발송 (현재 진행 중인 열차인 경우만)
        if self.current_event_id and event_id == self.current_event_id:
            self.sig_update_wheel_ui.emit(pos, s1, s2)