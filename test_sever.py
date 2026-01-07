import sys
import time
import zmq
import json
import uuid
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QComboBox, QRadioButton, QGroupBox, 
    QPushButton, QTextEdit, QButtonGroup
)
from PyQt5.QtCore import QThread, pyqtSignal

# ==================================================
# [설정] ZMQ 통신 주소
# ==================================================
PUSH_BIND = "tcp://*:5888"

# ==================================================
# [백그라운드] 시나리오 실행 스레드 (화면 멈춤 방지)
# ==================================================
class ScenarioWorker(QThread):
    log_signal = pyqtSignal(str)     # 로그 출력용 시그널
    finished_signal = pyqtSignal()   # 종료 알림 시그널

    def __init__(self, socket, data):
        super().__init__()
        self.sock = socket
        self.d = data  # UI에서 받아온 설정값들

    def _now_ms(self):
        return int(time.time() * 1000)

    def _make_event_id(self):
        return "car-{0}-{1}".format(self._now_ms(), uuid.uuid4().hex[:6])

    def run(self):
        try:
            event_id = self._make_event_id()
            car_no = self.d['car_no']
            
            # 1. [T=0] START
            start_packet = {
                "type": "car_event", "event": "START", "car_no": None,
                "event_id": event_id, "ts_ms": self._now_ms()
            }
            self.sock.send_json(start_packet)
            self.log_signal.emit(f"[T=0.0s] START (ID: {event_id})")
            
            time.sleep(2.0)

            # 2. [T=2] CAR_NO
            car_packet = {
                "type": "car_no", "event_id": event_id, 
                "car_no": car_no, "ts_ms": self._now_ms()
            }
            self.sock.send_json(car_packet)
            self.log_signal.emit(f"[T=2.0s] CAR_NO: {car_no}")
            
            time.sleep(1.0)

            # 3. [T=3] 1st Wheel (WS/DS)
            # 1st 전송 시: UI에서 설정한 1st값은 넣고, 2nd값은 0으로
            self._send_wheel("1st", event_id, car_no)
            self.log_signal.emit(f"[T=3.0s] 1st Wheel Data Sent")

            time.sleep(1.0)

            # 4. [T=4] 2nd Wheel (WS/DS)
            # 2nd 전송 시: 1st값은 0으로, UI에서 설정한 2nd값 넣기
            self._send_wheel("2nd", event_id, car_no)
            self.log_signal.emit(f"[T=4.0s] 2nd Wheel Data Sent")

            time.sleep(1.0) # 사이클 마무리 대기

        except Exception as e:
            self.log_signal.emit(f"[ERROR] {e}")
        finally:
            self.finished_signal.emit()

    def _send_wheel(self, src, event_id, car_no):
        """WS, DS 각각 패킷을 만들어 전송"""
        stop_flag = self.d['stop_flag']
        
        # 보낼 데이터 결정
        if src == "1st":
            w1_r, w1_p = self.d['ws_1_r'], self.d['ws_1_p']
            d1_r, d1_p = self.d['ds_1_r'], self.d['ds_1_p']
            w2_r, w2_p = 0, 0
            d2_r, d2_p = 0, 0
        else: # 2nd
            w1_r, w1_p = 0, 0
            d1_r, d1_p = 0, 0
            w2_r, w2_p = self.d['ws_2_r'], self.d['ws_2_p']
            d2_r, d2_p = self.d['ds_2_r'], self.d['ds_2_p']

        # WS Packet
        ws_pkt = {
            "type": "wheel_status", "pos": "WS", "src": src,
            "car_no": car_no, "stop_flag": stop_flag, "event_id": event_id, "ts_ms": self._now_ms(),
            "wheel1_rotation": int(w1_r), "wheel1_position": int(w1_p),
            "wheel2_rotation": int(w2_r), "wheel2_position": int(w2_p)
        }
        self.sock.send_json(ws_pkt)

        # DS Packet
        ds_pkt = {
            "type": "wheel_status", "pos": "DS", "src": src,
            "car_no": car_no, "stop_flag": stop_flag, "event_id": event_id, "ts_ms": self._now_ms(),
            "wheel1_rotation": int(d1_r), "wheel1_position": int(d1_p),
            "wheel2_rotation": int(d2_r), "wheel2_position": int(d2_p)
        }
        self.sock.send_json(ds_pkt)

# ==================================================
# [UI] 메인 윈도우
# ==================================================
class SenderWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("시나리오 수동 전송기 (Test Sender)")
        self.resize(600, 700)
        
        # ZMQ 초기화
        self.ctx = zmq.Context()
        self.sock = self.ctx.socket(zmq.PUSH)
        try:
            self.sock.bind(PUSH_BIND)
            self.zmq_status = f"Bind OK ({PUSH_BIND})"
        except Exception as e:
            self.zmq_status = f"Bind Fail: {e}"

        self.init_ui()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # 1. 상태 표시
        lbl_status = QLabel(f"통신 상태: {self.zmq_status}")
        lbl_status.setStyleSheet("font-weight: bold; color: blue;")
        layout.addWidget(lbl_status)

        # 2. 공통 설정 (대차번호, 정지 플래그)
        grp_common = QGroupBox("1. 기본 정보")
        lay_common = QHBoxLayout(grp_common)
        
        lay_common.addWidget(QLabel("대차 번호:"))
        self.edt_car_no = QLineEdit("123")
        lay_common.addWidget(self.edt_car_no)

        lay_common.addSpacing(20)
        lay_common.addWidget(QLabel("Stop Flag:"))
        self.rb_move = QRadioButton("0: 이동")
        self.rb_stop = QRadioButton("1: 정지")
        self.rb_move.setChecked(True)
        self.bg_stop = QButtonGroup()
        self.bg_stop.addButton(self.rb_move, 0)
        self.bg_stop.addButton(self.rb_stop, 1)
        lay_common.addWidget(self.rb_move)
        lay_common.addWidget(self.rb_stop)
        
        layout.addWidget(grp_common)

        # 3. 휠 데이터 설정 (1st / 2nd)
        # Helper function to create combos
        def make_combo():
            cb = QComboBox()
            cb.addItems(["0: 인식실패", "1: 정상(OK)", "2: 비정상(NG)"])
            cb.setCurrentIndex(1) # Default OK
            return cb

        # --- 1st Wheel ---
        grp_1st = QGroupBox("2. 1st Wheel 상태 설정")
        lay_1st = QHBoxLayout(grp_1st)
        
        # WS 1st
        lay_ws1 = QVBoxLayout()
        lay_ws1.addWidget(QLabel("[WS 1st]"))
        self.cb_ws1_r = make_combo()
        self.cb_ws1_p = make_combo()
        lay_ws1.addWidget(QLabel("회전(R):")); lay_ws1.addWidget(self.cb_ws1_r)
        lay_ws1.addWidget(QLabel("위치(P):")); lay_ws1.addWidget(self.cb_ws1_p)
        lay_1st.addLayout(lay_ws1)

        lay_1st.addSpacing(10)
        
        # DS 1st
        lay_ds1 = QVBoxLayout()
        lay_ds1.addWidget(QLabel("[DS 1st]"))
        self.cb_ds1_r = make_combo()
        self.cb_ds1_p = make_combo()
        lay_ds1.addWidget(QLabel("회전(R):")); lay_ds1.addWidget(self.cb_ds1_r)
        lay_ds1.addWidget(QLabel("위치(P):")); lay_ds1.addWidget(self.cb_ds1_p)
        lay_1st.addLayout(lay_ds1)
        
        layout.addWidget(grp_1st)

        # --- 2nd Wheel ---
        grp_2nd = QGroupBox("3. 2nd Wheel 상태 설정")
        lay_2nd = QHBoxLayout(grp_2nd)

        # WS 2nd
        lay_ws2 = QVBoxLayout()
        lay_ws2.addWidget(QLabel("[WS 2nd]"))
        self.cb_ws2_r = make_combo()
        self.cb_ws2_p = make_combo()
        lay_ws2.addWidget(QLabel("회전(R):")); lay_ws2.addWidget(self.cb_ws2_r)
        lay_ws2.addWidget(QLabel("위치(P):")); lay_ws2.addWidget(self.cb_ws2_p)
        lay_2nd.addLayout(lay_ws2)

        lay_2nd.addSpacing(10)

        # DS 2nd
        lay_ds2 = QVBoxLayout()
        lay_ds2.addWidget(QLabel("[DS 2nd]"))
        self.cb_ds2_r = make_combo()
        self.cb_ds2_p = make_combo()
        lay_ds2.addWidget(QLabel("회전(R):")); lay_ds2.addWidget(self.cb_ds2_r)
        lay_ds2.addWidget(QLabel("위치(P):")); lay_ds2.addWidget(self.cb_ds2_p)
        lay_2nd.addLayout(lay_ds2)

        layout.addWidget(grp_2nd)

        # 4. 전송 버튼
        self.btn_send = QPushButton("▶ 시나리오 시작 (5초 소요)")
        self.btn_send.setFixedHeight(50)
        self.btn_send.setStyleSheet("font-size: 16px; font-weight: bold; background-color: #4CAF50; color: white;")
        self.btn_send.clicked.connect(self.start_scenario)
        layout.addWidget(self.btn_send)

        # 5. 로그창
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)

    def log(self, msg):
        self.log_view.append(msg)
        # 스크롤 최하단으로
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def start_scenario(self):
        # 1. UI 값 읽기
        data = {
            "car_no": self.edt_car_no.text(),
            "stop_flag": self.bg_stop.checkedId(),
            # 1st
            "ws_1_r": self.cb_ws1_r.currentIndex(), "ws_1_p": self.cb_ws1_p.currentIndex(),
            "ds_1_r": self.cb_ds1_r.currentIndex(), "ds_1_p": self.cb_ds1_p.currentIndex(),
            # 2nd
            "ws_2_r": self.cb_ws2_r.currentIndex(), "ws_2_p": self.cb_ws2_p.currentIndex(),
            "ds_2_r": self.cb_ds2_r.currentIndex(), "ds_2_p": self.cb_ds2_p.currentIndex(),
        }

        self.log("-" * 30)
        self.log(f"시나리오 시작: 대차 {data['car_no']}")

        # 2. 버튼 비활성화 (중복 방지)
        self.btn_send.setEnabled(False)
        self.btn_send.setText("전송 중... (기다려주세요)")
        self.btn_send.setStyleSheet("background-color: gray; color: white;")

        # 3. 워커 스레드 시작
        self.worker = ScenarioWorker(self.sock, data)
        self.worker.log_signal.connect(self.log)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def on_finished(self):
        self.log("시나리오 완료.")
        self.btn_send.setEnabled(True)
        self.btn_send.setText("▶ 시나리오 시작 (5초 소요)")
        self.btn_send.setStyleSheet("font-size: 16px; font-weight: bold; background-color: #4CAF50; color: white;")

    def closeEvent(self, event):
        try:
            self.sock.close()
            self.ctx.term()
        except:
            pass
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = SenderWindow()
    win.show()
    sys.exit(app.exec_())