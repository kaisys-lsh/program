# main_run.py
import os
import sys
import json

from PyQt5 import uic, QtWidgets
from PyQt5.QtWidgets import QMainWindow, QApplication
from PyQt5.QtCore import Qt, QCoreApplication
from PyQt5.QtGui import QPixmap

from config.config import (
    DB_HOST, DB_PORT, DB_USER, DB_PW, CRY_USER, CRY_PW,
    CRY_A1_IP, CRY_A1_PORT, CRY_A1_USE_HTTPS,
    CRY_B1_IP, CRY_B1_PORT, CRY_B1_USE_HTTPS,
    CRY_A2_IP, CRY_A2_PORT, CRY_A2_USE_HTTPS,
    CRY_B2_IP, CRY_B2_PORT, CRY_B2_USE_HTTPS,
    CRY_INTERVAL_SEC, CRY_TIMEOUT_SEC,
    PULL_CONNECT1, PULL_CONNECT2, PULL_CONNECT3,
    RTSP_A1_IP, RTSP_B1_IP, RTSP_A2_IP, RTSP_B2_IP,
    RTSP_C1_IP, RTSP_C2_IP, RTSP_CAM_IP
)

from config.app_config import (
    UI_PATH, USE_DUMMY_CRY, USE_DUMMY_CAMERA,
    DELAY_COUNT, MAX_TABLE_ROWS
)

from utils.thresholds_utils import load_thresholds_from_json, save_thresholds_to_json
from utils.image_utils import set_label_pixmap_fill

from workers.db_writer import DbWriterThread
from ui.viewer_launcher import ViewerLauncher
from ui.button_manager import ButtonManager
from ui.table_manager import TableManager

from controllers.wagon_controller import WagonController
from controllers.wheel_controller import WheelController

# 카메라/ZMQ 스레드 선택
if USE_DUMMY_CAMERA:
    from test.zmq_rtsp_test import ZmqRecvThread, RtspThread
else:
    from workers.threads_zmq_rtsp import ZmqRecvThread, RtspThread

# CRY 스레드 선택
if USE_DUMMY_CRY:
    from test.cry_api_test import CryApiThread
else:
    from api.cry_api import CryApiThread


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        uic.loadUi(UI_PATH, self)

        # 프로젝트 루트(= main_run.py 위치)
        self.base_dir = os.path.dirname(os.path.abspath(__file__))

        # ----------------------------
        # thresholds
        # ----------------------------
        self.thresholds = load_thresholds_from_json()
        self.lineEdit_2.setText(str(self.thresholds["strong"]))
        self.lineEdit_3.setText(str(self.thresholds["mid"]))
        self.lineEdit_4.setText(str(self.thresholds["weak"]))

        # ----------------------------
        # DB writer
        # ----------------------------
        self.db_writer = DbWriterThread(DB_HOST, DB_PORT, DB_USER, DB_PW, parent=self)
        self.db_writer.start()

        # ----------------------------
        # UI managers
        # ----------------------------
        self.viewer_launcher = ViewerLauncher(self.base_dir)
        self.button_manager = ButtonManager(self, self.viewer_launcher, self.thresholds)
        self.table_manager = TableManager(self.tableWidget, self.thresholds, MAX_TABLE_ROWS)

        # ----------------------------
        # controllers
        # ----------------------------
        self.wheel_ctrl = WheelController(self.table_manager)
        self.wagon_ctrl = WagonController(
            delay_count=DELAY_COUNT,
            on_set_car_label=self._set_msg_1,
            on_record_ready=self._on_record_ready
        )

        # ----------------------------
        # repaint 버튼
        # ----------------------------
        self.pushButton_2.clicked.connect(self._button_repaint)

        # ----------------------------
        # ZMQ thread (★ 1개 포트만 사용)
        # ----------------------------
        self.zmq_thread = ZmqRecvThread(PULL_CONNECT1, parent=self)
        self.zmq_thread.text_ready.connect(self._on_zmq_text)
        self.zmq_thread.start()

        # ----------------------------
        # RTSP threads
        # ----------------------------
        self.rtspCAM1 = RtspThread(RTSP_CAM_IP, name="CAM1", parent=self)
        self.rtspCAM1.frame_ready.connect(self._on_cam1_frame)
        self.rtspCAM1.start()

        self.rtspA1 = RtspThread(RTSP_A1_IP, name="WS1", parent=self)
        self.rtspA1.frame_ready.connect(self._on_ws1_frame)
        self.rtspA1.start()

        self.rtspB1 = RtspThread(RTSP_B1_IP, name="DS1", parent=self)
        self.rtspB1.frame_ready.connect(self._on_ds1_frame)
        self.rtspB1.start()

        self.rtspA2 = RtspThread(RTSP_A2_IP, name="WS2", parent=self)
        self.rtspA2.frame_ready.connect(self._on_ws2_frame)
        self.rtspA2.start()

        self.rtspB2 = RtspThread(RTSP_B2_IP, name="DS2", parent=self)
        self.rtspB2.frame_ready.connect(self._on_ds2_frame)
        self.rtspB2.start()

        self.rtsp_wheel1 = RtspThread(RTSP_C1_IP, name="Wheel_WS", parent=self)
        self.rtsp_wheel1.frame_ready.connect(self._on_wheel_ws_frame)
        self.rtsp_wheel1.start()

        self.rtsp_wheel2 = RtspThread(RTSP_C2_IP, name="Wheel_DS", parent=self)
        self.rtsp_wheel2.frame_ready.connect(self._on_wheel_ds_frame)
        self.rtsp_wheel2.start()

        # ----------------------------
        # CRY threads
        # ----------------------------
        self.cry_ws1 = CryApiThread(
            ip=CRY_A1_IP, port=CRY_A1_PORT, user=CRY_USER, pw=CRY_PW,
            use_https=CRY_A1_USE_HTTPS,
            interval_sec=CRY_INTERVAL_SEC, timeout_sec=CRY_TIMEOUT_SEC,
            parent=self
        )
        self.cry_ws1.db_ready.connect(self._on_ws1_db)
        self.cry_ws1.start()

        self.cry_ds1 = CryApiThread(
            ip=CRY_B1_IP, port=CRY_B1_PORT, user=CRY_USER, pw=CRY_PW,
            use_https=CRY_B1_USE_HTTPS,
            interval_sec=CRY_INTERVAL_SEC, timeout_sec=CRY_TIMEOUT_SEC,
            parent=self
        )
        self.cry_ds1.db_ready.connect(self._on_ds1_db)
        self.cry_ds1.start()

        self.cry_ws2 = CryApiThread(
            ip=CRY_A2_IP, port=CRY_A2_PORT, user=CRY_USER, pw=CRY_PW,
            use_https=CRY_A2_USE_HTTPS,
            interval_sec=CRY_INTERVAL_SEC, timeout_sec=CRY_TIMEOUT_SEC,
            parent=self
        )
        self.cry_ws2.db_ready.connect(self._on_ws2_db)
        self.cry_ws2.start()

        self.cry_ds2 = CryApiThread(
            ip=CRY_B2_IP, port=CRY_B2_PORT, user=CRY_USER, pw=CRY_PW,
            use_https=CRY_B2_USE_HTTPS,
            interval_sec=CRY_INTERVAL_SEC, timeout_sec=CRY_TIMEOUT_SEC,
            parent=self
        )
        self.cry_ds2.db_ready.connect(self._on_ds2_db)
        self.cry_ds2.start()

    # ---------------- UI helpers ----------------
    def _set_msg_1(self, text):
        self.msg_1.setText(str(text))

    # ---------------- ZMQ router (★ JSON type 분기) ----------------
    def _on_zmq_text(self, text):
        if not isinstance(text, str):
            return

        s = text.strip()
        if not s:
            return

        try:
            data = json.loads(s)
        except Exception:
            return

        msg_type = str(data.get("type", "")).strip()

        # 1) 대차 이벤트
        if msg_type == "car_event":
            ev = str(data.get("event", "")).strip()

            if ev == "START":
                self.wagon_ctrl.on_cam_message("START")
                return

            if ev == "END":
                car_no = str(data.get("car_no", "")).strip()

                # 서버 미검출: "FFF" → 기존 wagon 로직 호환: "NONE"
                if (not car_no) or (car_no == "FFF"):
                    self.wagon_ctrl.on_cam_message("NONE")
                else:
                    self.wagon_ctrl.on_cam_message(car_no)

                return

            return

        # 2) 휠 이벤트 / 누적 업데이트
        if (msg_type == "wheel_event") or (msg_type == "car_update"):
            pos = str(data.get("pos", "")).strip()
            if pos == "WS" or pos == "DS":
                self._on_wheel_msg(pos, s)
            return

    # ---------------- frames ----------------
    def _on_cam1_frame(self, qimg, bgr):
        set_label_pixmap_fill(self.image_1, QPixmap.fromImage(qimg))
        self.wagon_ctrl.update_latest_frame("cam1", bgr)  # ✅ CAM1 저장

    def _on_ws1_frame(self, qimg, bgr):
        set_label_pixmap_fill(self.image_2, QPixmap.fromImage(qimg))
        self.wagon_ctrl.update_latest_frame("ws1", bgr)

    def _on_ds1_frame(self, qimg, bgr):
        set_label_pixmap_fill(self.image_3, QPixmap.fromImage(qimg))
        self.wagon_ctrl.update_latest_frame("ds1", bgr)

    def _on_ws2_frame(self, qimg, bgr):
        set_label_pixmap_fill(self.image_4, QPixmap.fromImage(qimg))
        self.wagon_ctrl.update_latest_frame("ws2", bgr)

    def _on_ds2_frame(self, qimg, bgr):
        set_label_pixmap_fill(self.image_5, QPixmap.fromImage(qimg))
        self.wagon_ctrl.update_latest_frame("ds2", bgr)

    def _on_wheel_ws_frame(self, qimg, bgr):
        set_label_pixmap_fill(self.image_6, QPixmap.fromImage(qimg))
        self.wheel_ctrl.update_latest_frame("WS", bgr)    # ✅ Wheel WS 저장

    def _on_wheel_ds_frame(self, qimg, bgr):
        set_label_pixmap_fill(self.image_7, QPixmap.fromImage(qimg))
        self.wheel_ctrl.update_latest_frame("DS", bgr)    # ✅ Wheel DS 저장

    # ---------------- dB ----------------
    def _on_ws1_db(self, v):
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        self.msg_2.setText(str(round(fv, 2)))
        self.wagon_ctrl.on_db("ws1", fv)

    def _on_ds1_db(self, v):
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        self.msg_3.setText(str(round(fv, 2)))
        self.wagon_ctrl.on_db("ds1", fv)

    def _on_ws2_db(self, v):
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        self.msg_6.setText(str(round(fv, 2)))
        self.wagon_ctrl.on_db("ws2", fv)

    def _on_ds2_db(self, v):
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        self.msg_5.setText(str(round(fv, 2)))
        self.wagon_ctrl.on_db("ds2", fv)

    # ---------------- wheel ZMQ ----------------
    def _on_wheel_msg(self, pos, text):
        res = self.wheel_ctrl.handle_message(pos, text)
        if res is None:
            return

        if pos == "WS":
            self.msg_4.setText("1st:{0}".format(res["status_1st"]))
            self.msg_8.setText("2nd:{0}".format(res["status_2nd"]))
        else:
            self.msg_7.setText("1st:{0}".format(res["status_1st"]))
            self.msg_9.setText("2nd:{0}".format(res["status_2nd"]))

    # ---------------- record ready (핵심) ----------------
    def _on_record_ready(self, rec):
        car_no_str = str(rec.get("car_no", "")).strip()
        label_text = "N" if rec.get("car_no") == "none" else car_no_str

        # 1) 테이블 insert
        self.table_manager.insert_record(rec)

        # 2) pending wheel 테이블 반영
        self.wheel_ctrl.apply_pending_to_table(car_no_str)

        # 3) record에 wheel 붙이고 overall 계산
        overall = self.wheel_ctrl.attach_wheel_info_to_record(rec)

        # 4) 버튼색은 max dB
        max_db = max(
            float(rec.get("ws1_db", 0.0)),
            float(rec.get("ds1_db", 0.0)),
            float(rec.get("ws2_db", 0.0)),
            float(rec.get("ds2_db", 0.0)),
        )
        self.button_manager.push_front(label_text, max_db, overall)

        # 5) DB 저장
        self.db_writer.enqueue(rec)

    # ---------------- thresholds repaint ----------------
    def _button_repaint(self):
        def safe_float(le, d):
            try:
                return float(le.text())
            except Exception:
                return d

        strong = safe_float(self.lineEdit_2, self.thresholds.get("strong", 5.0))
        mid = safe_float(self.lineEdit_3, self.thresholds.get("mid", 4.0))
        weak = safe_float(self.lineEdit_4, self.thresholds.get("weak", 3.0))

        vals = sorted([weak, mid, strong])
        self.thresholds["weak"] = vals[0]
        self.thresholds["mid"] = vals[1]
        self.thresholds["strong"] = vals[2]

        save_thresholds_to_json(self.thresholds)

        self.button_manager.set_thresholds(self.thresholds)
        self.table_manager.set_thresholds(self.thresholds)

        self.button_manager.repaint_all()
        self.table_manager.repaint_db_cells()

    # ---------------- close ----------------
    def closeEvent(self, event):
        left = self.wagon_ctrl.flush_remaining_records()
        for rec in left:
            self.db_writer.enqueue(rec)

        workers = [
            self.zmq_thread,
            self.rtspA1, self.rtspB1, self.rtspA2, self.rtspB2,
            self.cry_ws1, self.cry_ds1, self.cry_ws2, self.cry_ds2,
            self.rtsp_wheel1, self.rtsp_wheel2, self.rtspCAM1
        ]

        for w in workers:
            try:
                w.stop()
                w.wait(2000)
            except Exception:
                pass

        try:
            self.db_writer.stop()
            self.db_writer.wait(3000)
        except Exception:
            pass

        event.accept()


if __name__ == "__main__":
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
