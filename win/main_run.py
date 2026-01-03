# win/main_run.py
# -*- coding: utf-8 -*-
import sys
import os

from PyQt5 import uic
from PyQt5.QtWidgets import QMainWindow, QApplication
from PyQt5.QtCore import Qt, QCoreApplication, pyqtSlot

# Config
from config.config import (
    DB_HOST, DB_PORT, DB_USER, DB_PW,
    CRY_USER, CRY_PW, UI_PATH, DELAY_COUNT, SHOW_LIVE_VIDEO,
    # IPs
    CRY_A1_IP, CRY_A1_PORT, CRY_A1_USE_HTTPS,
    CRY_B1_IP, CRY_B1_PORT, CRY_B1_USE_HTTPS,
    CRY_A2_IP, CRY_A2_PORT, CRY_A2_USE_HTTPS,
    CRY_B2_IP, CRY_B2_PORT, CRY_B2_USE_HTTPS,
    RTSP_CAM_IP, RTSP_A1_IP, RTSP_B1_IP, RTSP_A2_IP, RTSP_B2_IP, RTSP_C1_IP, RTSP_C2_IP
)

from utils.color_json_utils import load_thresholds_from_json, save_thresholds_to_json

# Workers & Managers
from workers.db_worker import DbWriterThread, DbPollerThread
from workers.threads_rtsp import RtspThread
from api.cry_api import CryApiThread

from managers.zmq_manager import ZmqManager
from managers.ui_manager import MainUiController        # ✅ 통합된 UI 매니저
from controllers.wagon_controller import WagonController


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        uic.loadUi(UI_PATH, self)
        
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.thresholds = load_thresholds_from_json()

        # ------------------------------------------------
        # 1. UI 컨트롤러 초기화 (가장 먼저)
        # ------------------------------------------------
        self.ui = MainUiController(self, self.base_dir, self.thresholds)
        self._init_ui_values() # 초기값 세팅

        # ------------------------------------------------
        # 2. 로직/DB 스레드
        # ------------------------------------------------
        self.db_writer = DbWriterThread(DB_HOST, DB_PORT, DB_USER, DB_PW, parent=self)
        self.db_writer.start()

        self.wagon_ctrl = WagonController(self.db_writer.enqueue, DELAY_COUNT)

        self.zmq_manager = ZmqManager(self.wagon_ctrl, self.db_writer)
        self.zmq_manager.sig_update_wheel_ui.connect(self.ui.update_wheel_status_label) # ✅ UI로 바로 연결
        self.zmq_manager.sig_clear_ui.connect(self.ui.clear_wheel_labels)               # ✅ UI로 바로 연결
        self.zmq_manager.start()

        self.db_poller = DbPollerThread(DB_HOST, DB_PORT, DB_USER, DB_PW, parent=self)
        self.db_poller.record_ready.connect(self.ui.add_db_record)                      # ✅ UI로 바로 연결
        self.db_poller.start()

        # ------------------------------------------------
        # 3. 하드웨어 스레드 (카메라/센서)
        # ------------------------------------------------
        self.threads = []
        self._start_cameras()
        self._start_sensors()

        # 버튼 이벤트
        self.pushButton_2.clicked.connect(self._on_click_apply_thresholds)

    # --- Initializers ---
    def _start_cameras(self):
        # (IP, Name, CamID) - UI 위젯은 이제 필요 없음(ID로 매핑)
        cams = [
            (RTSP_CAM_IP, "CAM1", "cam1"),
            (RTSP_A1_IP, "WS1", "ws1"), (RTSP_B1_IP, "DS1", "ds1"),
            (RTSP_A2_IP, "WS2", "ws2"), (RTSP_B2_IP, "DS2", "ds2"),
            (RTSP_C1_IP, "W_WS", "wheel_ws"), (RTSP_C2_IP, "W_DS", "wheel_ds"),
        ]
        for ip, name, cid in cams:
            t = RtspThread(ip, name, self)
            t.frame_ready.connect(lambda q, b, c=cid: self._on_frame(c, q, b))
            t.start()
            self.threads.append(t)

    def _start_sensors(self):
        crys = [
            (CRY_A1_IP, CRY_A1_PORT, CRY_A1_USE_HTTPS, "ws1"),
            (CRY_B1_IP, CRY_B1_PORT, CRY_B1_USE_HTTPS, "ds1"),
            (CRY_A2_IP, CRY_A2_PORT, CRY_A2_USE_HTTPS, "ws2"),
            (CRY_B2_IP, CRY_B2_PORT, CRY_B2_USE_HTTPS, "ds2"),
        ]
        for ip, port, https, cid in crys:
            t = CryApiThread(ip, port, CRY_USER, CRY_PW, https, parent=self)
            t.db_ready.connect(lambda v, c=cid: self._on_sensor(c, v))
            t.start()
            self.threads.append(t)

    # --- Callbacks ---
    def _on_frame(self, cam_id, qimg, bgr):
        if SHOW_LIVE_VIDEO:
            self.ui.update_live_image(cam_id, qimg) # ✅ UI 위임
        self.wagon_ctrl.update_latest_frame(cam_id, bgr)

    def _on_sensor(self, cam_id, val):
        try: fv = float(val)
        except: fv = 0.0
        self.ui.update_sensor_text(cam_id, fv)      # ✅ UI 위임
        self.wagon_ctrl.on_db(cam_id, fv)

    def _on_click_apply_thresholds(self):
        new_vals = self.ui.get_threshold_inputs()
        if new_vals:
            final_thr = self.ui.apply_new_thresholds(new_vals)
            save_thresholds_to_json(final_thr)

    def _init_ui_values(self):
        # 초기 라인에디트 값 설정도 필요하다면 UI Manager에 위임 가능하지만,
        # 간단히 여기서 처리하거나 UI Manager init에서 처리해도 됨.
        try:
            self.lineEdit_2.setText(str(self.thresholds.get("strong", 5.0)))
            self.lineEdit_3.setText(str(self.thresholds.get("mid", 4.0)))
            self.lineEdit_4.setText(str(self.thresholds.get("weak", 3.0)))
        except: pass

    def closeEvent(self, event):
        self.zmq_manager.stop()
        self.db_poller.stop()
        self.db_writer.stop()
        for t in self.threads: t.stop()
        event.accept()

if __name__ == "__main__":
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())