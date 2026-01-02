# zmq_pyqt5_viewer.py
# ------------------------------------------------------------
# ZMQ 수신 테스트 (PyQt5)
# - 라벨1: car_no
# - 라벨2: WS 1st
# - 라벨3: WS 2nd
# - 라벨4: DS 1st
# - 라벨5: DS 2nd
# - 큰 라벨(텍스트박스): 수신 JSON 원문 pretty 출력
# + 터미널에도 print 출력
# ------------------------------------------------------------

import sys
import json
import zmq

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QTextEdit, QVBoxLayout, QGridLayout
)
from PyQt5.QtCore import QTimer


ZMQ_PULL_CONNECT = "tcp://127.0.0.1:5888"


def _fmt_wheel(rot, pos):
    # rot/pos: 0 fail / 1 good / 2 bad
    return f"rot={rot}, pos={pos}"


class ZmqViewer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ZMQ Viewer (Car/Wheel)")

        # ---- UI ----
        self.lbl_car = QLabel("car_no: -")
        self.lbl_ws1 = QLabel("WS 1st: -")
        self.lbl_ws2 = QLabel("WS 2nd: -")
        self.lbl_ds1 = QLabel("DS 1st: -")
        self.lbl_ds2 = QLabel("DS 2nd: -")

        self.txt_json = QTextEdit()
        self.txt_json.setReadOnly(True)
        self.txt_json.setMinimumHeight(250)

        grid = QGridLayout()
        grid.addWidget(QLabel("Label1 (car_no)"), 0, 0)
        grid.addWidget(self.lbl_car, 0, 1)

        grid.addWidget(QLabel("Label2 (WS 1st)"), 1, 0)
        grid.addWidget(self.lbl_ws1, 1, 1)

        grid.addWidget(QLabel("Label3 (WS 2nd)"), 2, 0)
        grid.addWidget(self.lbl_ws2, 2, 1)

        grid.addWidget(QLabel("Label4 (DS 1st)"), 3, 0)
        grid.addWidget(self.lbl_ds1, 3, 1)

        grid.addWidget(QLabel("Label5 (DS 2nd)"), 4, 0)
        grid.addWidget(self.lbl_ds2, 4, 1)

        layout = QVBoxLayout()
        layout.addLayout(grid)
        layout.addWidget(QLabel("JSON (raw pretty)"))
        layout.addWidget(self.txt_json)
        self.setLayout(layout)

        # ---- State ----
        self.last_car_no = "-"
        self.ws_state = {"1st": None, "2nd": None}
        self.ds_state = {"1st": None, "2nd": None}

        # ---- ZMQ ----
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.PULL)
        self.sock.connect(ZMQ_PULL_CONNECT)
        self.sock.RCVTIMEO = 0  # non-blocking

        # ---- Poll Timer ----
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_zmq)
        self.timer.start(10)

    def closeEvent(self, event):
        try:
            self.timer.stop()
        except Exception:
            pass
        try:
            self.sock.close(0)
        except Exception:
            pass
        try:
            self.ctx.term()
        except Exception:
            pass
        event.accept()

    def poll_zmq(self):
        while True:
            try:
                msg = self.sock.recv_string(flags=zmq.NOBLOCK)
            except zmq.Again:
                break
            except Exception as e:
                self.txt_json.setPlainText(f"[ZMQ ERROR] {e}")
                print(f"[ZMQ ERROR] {e}", flush=True)
                break

            self.on_message(msg)

    def on_message(self, msg_str):
        # --- JSON 파싱/pretty ---
        try:
            obj = json.loads(msg_str)
            pretty = json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            obj = None
            pretty = msg_str

        # --- UI 표시 ---
        self.txt_json.setPlainText(pretty)

        # --- 터미널 출력 (추가) ---
        # pretty가 너무 길면 원문만/한줄로 바꿔도 됨. 일단 pretty 출력.
        print(pretty, flush=True)

        if not isinstance(obj, dict):
            return

        # 1) car_event END면 car_no 업데이트
        if obj.get("type") == "car_event":
            if obj.get("event") == "END":
                car_no = str(obj.get("car_no", "-"))
                self.last_car_no = car_no
                self.lbl_car.setText(f"car_no: {car_no}")
            return

        # 2) wheel_event / car_update 처리
        if obj.get("type") in ("wheel_event", "car_update"):
            pos = str(obj.get("pos", "")).upper().strip()
            if pos not in ("WS", "DS"):
                return

            car_no = obj.get("wheel_car_no")
            if car_no is None:
                car_no = obj.get("car_no")
            if car_no is not None:
                self.last_car_no = str(car_no)
                self.lbl_car.setText(f"car_no: {self.last_car_no}")

            r1 = obj.get("wheel_1st_rotation")
            p1 = obj.get("wheel_1st_position")
            r2 = obj.get("wheel_2nd_rotation")
            p2 = obj.get("wheel_2nd_position")

            if (r1 is not None) and (p1 is not None):
                if pos == "WS":
                    self.ws_state["1st"] = (int(r1), int(p1))
                else:
                    self.ds_state["1st"] = (int(r1), int(p1))

            if (r2 is not None) and (p2 is not None):
                if pos == "WS":
                    self.ws_state["2nd"] = (int(r2), int(p2))
                else:
                    self.ds_state["2nd"] = (int(r2), int(p2))

            self.refresh_labels()

    def refresh_labels(self):
        ws1 = self.ws_state["1st"]
        ws2 = self.ws_state["2nd"]
        ds1 = self.ds_state["1st"]
        ds2 = self.ds_state["2nd"]

        self.lbl_ws1.setText("WS 1st: " + (_fmt_wheel(ws1[0], ws1[1]) if ws1 else "-"))
        self.lbl_ws2.setText("WS 2nd: " + (_fmt_wheel(ws2[0], ws2[1]) if ws2 else "-"))
        self.lbl_ds1.setText("DS 1st: " + (_fmt_wheel(ds1[0], ds1[1]) if ds1 else "-"))
        self.lbl_ds2.setText("DS 2nd: " + (_fmt_wheel(ds2[0], ds2[1]) if ds2 else "-"))


def main():
    app = QApplication(sys.argv)
    w = ZmqViewer()
    w.resize(700, 450)
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
