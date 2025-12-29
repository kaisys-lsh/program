# main_run.py
# -*- coding: utf-8 -*-
import os
import sys
import json
from datetime import datetime

from PyQt5 import uic
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
    PULL_CONNECT1,
    RTSP_A1_IP, RTSP_B1_IP, RTSP_A2_IP, RTSP_B2_IP,
    RTSP_C1_IP, RTSP_C2_IP, RTSP_CAM_IP
)

from config.app_config import (
    UI_PATH, USE_DUMMY_CRY, USE_DUMMY_CAMERA,
    DELAY_COUNT, MAX_TABLE_ROWS,
    SNAPSHOT_SEC, SHOW_LIVE_VIDEO
)

from utils.thresholds_utils import load_thresholds_from_json, save_thresholds_to_json
from utils.image_utils import set_label_pixmap_fill
from utils.wheel_status_utils import judge_one_wheel, combine_overall_wheel_status

from workers.db_writer import DbWriterThread
from workers.db_poller import DbPollerThread

from ui.viewer_launcher import ViewerLauncher
from ui.button_manager import ButtonManager
from ui.table_manager import TableManager
from controllers.wagon_controller import WagonController
from utils.zmq_debug_printer import print_zmq_debug

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

        self.base_dir = os.path.dirname(os.path.abspath(__file__))

        # ---------------- thresholds ----------------
        self.thresholds = load_thresholds_from_json()
        self.lineEdit_2.setText(str(self.thresholds["strong"]))
        self.lineEdit_3.setText(str(self.thresholds["mid"]))
        self.lineEdit_4.setText(str(self.thresholds["weak"]))

        # ---------------- DB writer ----------------
        self.db_writer = DbWriterThread(DB_HOST, DB_PORT, DB_USER, DB_PW, parent=self)
        self.db_writer.start()

        # ---------------- DB poller (표시 담당) ----------------
        # ✅ "DB가 큐 역할" + "완성 row만 HMI 표시"
        # ✅ 미완성 영원 방지: car_no / wheel / zone1 타임아웃 강제완료 포함
        self.db_poller = DbPollerThread(
            DB_HOST, DB_PORT, DB_USER, DB_PW,
            poll_interval_sec=0.2,
            skip_existing_completed=True,

            enable_force_finalize=True,
            force_car_no_sec=5.0,
            force_wheel_sec=5.0,
            force_zone1_sec=5.0,
            force_zone2_sec=None,   # zone2는 기본 강제완료 안함(7대 지연이 정상이라서)

            parent=self
        )
        self.db_poller.record_ready.connect(self._on_db_record_ready)
        self.db_poller.start()

        # ---------------- UI managers ----------------
        self.viewer_launcher = ViewerLauncher(self.base_dir)
        self.button_manager = ButtonManager(self, self.viewer_launcher, self.thresholds)
        self.table_manager = TableManager(self.tableWidget, self.thresholds, MAX_TABLE_ROWS)

        # ✅ 현재 진행 중 대차 event_id (라벨 보호용)
        self.current_event_id = ""

        # ---------------- Wagon controller (저장 patch 생성 담당) ----------------
        # ✅ 핵심 변경:
        # - _db_cache 제거
        # - wagon_controller가 만든 patch(dict)를 그대로 db_writer.enqueue로 보냄
        self.wagon_ctrl = WagonController(
            delay_count=DELAY_COUNT,
            snapshot_sec=SNAPSHOT_SEC,
            on_set_car_label=self._set_msg_1,
            on_stage1_ready=self._enqueue_db_patch,   # ✅ 바로 DB patch 저장
            db_host=DB_HOST,
            db_port=DB_PORT,
            db_user=DB_USER,
            db_pw=DB_PW,
            db_name="posco",
            table_name="data",
        )

        # ---------------- repaint 버튼 ----------------
        self.pushButton_2.clicked.connect(self._button_repaint)

        # ---------------- ZMQ ----------------
        self.zmq_thread = ZmqRecvThread(PULL_CONNECT1, parent=self)
        self.zmq_thread.text_ready.connect(self._on_zmq_text)
        self.zmq_thread.start()

        # ---------------- RTSP ----------------
        def start_rtsp_thread(ip, name, label, cam_id):
            t = RtspThread(ip, name=name, parent=self)
            t.frame_ready.connect(lambda q, b: self._on_frame(cam_id, label, q, b))
            t.start()
            return t

        self.rtspCAM1 = start_rtsp_thread(RTSP_CAM_IP, "CAM1", self.image_1, "cam1")
        self.rtspWS1 = start_rtsp_thread(RTSP_A1_IP, "WS1", self.image_2, "ws1")
        self.rtspDS1 = start_rtsp_thread(RTSP_B1_IP, "DS1", self.image_3, "ds1")
        self.rtspWS2 = start_rtsp_thread(RTSP_A2_IP, "WS2", self.image_4, "ws2")
        self.rtspDS2 = start_rtsp_thread(RTSP_B2_IP, "DS2", self.image_5, "ds2")
        self.rtspWheelWS = start_rtsp_thread(RTSP_C1_IP, "Wheel_WS", self.image_6, "wheel_ws")
        self.rtspWheelDS = start_rtsp_thread(RTSP_C2_IP, "Wheel_DS", self.image_7, "wheel_ds")

        # ---------------- CRY threads (dB) ----------------
        def start_cry_thread(ip, port, user, pw, use_https, cam_id, label):
            t = CryApiThread(
                ip=ip, port=port, user=user, pw=pw,
                use_https=use_https,
                interval_sec=CRY_INTERVAL_SEC, timeout_sec=CRY_TIMEOUT_SEC,
                parent=self
            )
            t.db_ready.connect(lambda v: self._on_db(cam_id, v, label))
            t.start()
            return t

        self.cry_ws1 = start_cry_thread(CRY_A1_IP, CRY_A1_PORT, CRY_USER, CRY_PW, CRY_A1_USE_HTTPS, "ws1", self.msg_2)
        self.cry_ds1 = start_cry_thread(CRY_B1_IP, CRY_B1_PORT, CRY_USER, CRY_PW, CRY_B1_USE_HTTPS, "ds1", self.msg_3)
        self.cry_ws2 = start_cry_thread(CRY_A2_IP, CRY_A2_PORT, CRY_USER, CRY_PW, CRY_A2_USE_HTTPS, "ws2", self.msg_6)
        self.cry_ds2 = start_cry_thread(CRY_B2_IP, CRY_B2_PORT, CRY_USER, CRY_PW, CRY_B2_USE_HTTPS, "ds2", self.msg_5)

    # ---------------- UI helpers ----------------
    def _set_msg_1(self, text):
        try:
            self.msg_1.setText(str(text))
        except Exception:
            pass

    def _safe_set_label_path(self, label, path):
        if not path:
            return
        try:
            pm = QPixmap(path)
            if not pm.isNull():
                set_label_pixmap_fill(label, pm)
        except Exception:
            pass

    def _clear_wheel_labels(self):
        try:
            self.msg_4.setText("")
            self.msg_8.setText("")
            self.msg_7.setText("")
            self.msg_9.setText("")
        except Exception:
            pass

    # ---------------- DB patch enqueue ----------------
    def _enqueue_db_patch(self, patch):
        """
        ✅ wagon_controller가 만든 patch(dict)를 그대로 DB에 저장
        - db_writer가 "부분 patch" 업데이트를 지원하므로 _db_cache가 필요 없음
        """
        if not isinstance(patch, dict):
            return
        try:
            self.db_writer.enqueue(patch)
        except Exception:
            pass

    # ---------------- frames ----------------
    def _on_frame(self, cam_id, label, qimg, bgr):
        if SHOW_LIVE_VIDEO:
            try:
                set_label_pixmap_fill(label, QPixmap.fromImage(qimg))
            except Exception:
                pass
        self.wagon_ctrl.update_latest_frame(cam_id, bgr)

    # ---------------- dB ----------------
    def _on_db(self, cam_id, v, label_widget):
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        try:
            label_widget.setText(str(round(fv, 2)))
        except Exception:
            pass
        self.wagon_ctrl.on_db(cam_id, fv)

    # ---------------- ZMQ ----------------
    def _on_zmq_text(self, text):
        print_zmq_debug(text)
        if not isinstance(text, str):
            return

        s = text.strip()
        if not s:
            return

        # 여러 줄 JSON도 처리
        if "\n" in s:
            lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
        else:
            lines = [s]

        for one in lines:
            try:
                data = json.loads(one)
            except Exception:
                continue

            mtype = str(data.get("type", "")).strip().lower()
            eid = str(data.get("event_id", "") or "").strip()

            if mtype == "car_event":
                ev = str(data.get("event", "")).strip().upper()

                # 현재 대차 event_id 추적 + 라벨 초기화
                if ev == "START" and eid:
                    self.current_event_id = eid
                    self._clear_wheel_labels()

                # END가 오면 현재 대차를 비움(원하면 유지해도 됨)
                if ev == "END" and eid and self.current_event_id == eid:
                    self.current_event_id = ""

                self.wagon_ctrl.on_car_event(data)
                continue

            if mtype == "car_no":
                self.wagon_ctrl.on_car_no(data)
                continue

            if mtype in ("wheel_status", "wheel_event", "car_update"):
                self._handle_wheel_like_event(data)
                continue

    # ---------------- wheel event (DB 저장만 + 현재 대차 라벨만 표시) ----------------
    def _handle_wheel_like_event(self, data):
        pos = str(data.get("pos", "")).strip().upper()
        event_id = str(data.get("event_id", "") or "").strip()
        if not pos or not event_id:
            return

        car_no = data.get("car_no") or data.get("wheel_car_no") or "none"
        car_no_str = str(car_no).strip()

        wheel = data.get("wheel", {})
        if isinstance(wheel, dict) and wheel:
            w1_rot = wheel.get("wheel_1st_rotation", 0)
            w1_pos = wheel.get("wheel_1st_position", 0)
            w2_rot = wheel.get("wheel_2nd_rotation", 0)
            w2_pos = wheel.get("wheel_2nd_position", 0)
        else:
            w1_rot = data.get("wheel_1st_rotation", data.get("wheel1_rotation", 0))
            w1_pos = data.get("wheel_1st_position", data.get("wheel1_position", 0))
            w2_rot = data.get("wheel_2nd_rotation", data.get("wheel2_rotation", 0))
            w2_pos = data.get("wheel_2nd_position", data.get("wheel2_position", 0))

        status_1st = judge_one_wheel(w1_rot, w1_pos)
        status_2nd = judge_one_wheel(w2_rot, w2_pos)

        # ✅ DB 저장(항상)
        self.wagon_ctrl.on_wheel_status(event_id, pos, status_1st, status_2nd, car_no_str)

        # ✅ 라벨은 "현재 대차"일 때만 표시
        if self.current_event_id and event_id == self.current_event_id:
            try:
                if pos == "WS":
                    self.msg_4.setText(status_1st)
                    self.msg_8.setText(status_2nd)
                elif pos == "DS":
                    self.msg_7.setText(status_1st)
                    self.msg_9.setText(status_2nd)
            except Exception:
                pass

    # ---------------- DB poller -> 표시 ----------------
    def _on_db_record_ready(self, rec):
        """
        rec는 DB에서 읽은 '완성 row'.
        ✅ 이제 여기서만 테이블/버튼/썸네일 표시한다.
        """
        if not isinstance(rec, dict):
            return

        overall = combine_overall_wheel_status(
            rec.get("ws_wheel1_status", ""),
            rec.get("ws_wheel2_status", ""),
            rec.get("ds_wheel1_status", ""),
            rec.get("ds_wheel2_status", ""),
        )
        rec["wheel_overall"] = overall

        # 테이블 insert
        self.table_manager.insert_record(rec)

        # 버튼
        car_no_str = str(rec.get("car_no", "none")).strip()
        label_text = car_no_str if car_no_str.lower() != "none" else "N"

        try:
            max_db = max(
                float(rec.get("ws1_db", 0.0)),
                float(rec.get("ds1_db", 0.0)),
                float(rec.get("ws2_db", 0.0)),
                float(rec.get("ds2_db", 0.0)),
            )
        except Exception:
            max_db = 0.0

        self.button_manager.push_front(label_text, max_db, overall)

        # 썸네일
        self._safe_set_label_path(self.image_1, rec.get("img_car_path", ""))
        self._safe_set_label_path(self.image_2, rec.get("img_ws1_path", ""))
        self._safe_set_label_path(self.image_3, rec.get("img_ds1_path", ""))
        self._safe_set_label_path(self.image_4, rec.get("img_ws2_path", ""))
        self._safe_set_label_path(self.image_5, rec.get("img_ds2_path", ""))
        self._safe_set_label_path(self.image_6, rec.get("img_ws_wheel_path", ""))
        self._safe_set_label_path(self.image_7, rec.get("img_ds_wheel_path", ""))

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
        workers = [
            self.zmq_thread,
            self.rtspWS1, self.rtspDS1, self.rtspWS2, self.rtspDS2,
            self.rtspWheelWS, self.rtspWheelDS, self.rtspCAM1,
            self.cry_ws1, self.cry_ds1, self.cry_ws2, self.cry_ds2,
        ]

        for w in workers:
            try:
                w.stop()
                w.wait(2000)
            except Exception:
                pass

        try:
            self.db_poller.stop()
            self.db_poller.wait(2000)
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
