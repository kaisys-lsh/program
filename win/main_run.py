# main_run.py
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
from utils.wheel_status_utils import judge_one_wheel

from workers.db_writer import DbWriterThread
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
        # Wagon controller (핵심)
        # ----------------------------
        self.wagon_ctrl = WagonController(
            delay_count=DELAY_COUNT,
            snapshot_sec=SNAPSHOT_SEC,
            on_set_car_label=self._set_msg_1,
            on_stage1_ready=self._on_stage1_ready,
            on_final_ready=self._on_final_ready
        )

        # ----------------------------
        # repaint 버튼
        # ----------------------------
        self.pushButton_2.clicked.connect(self._button_repaint)

        # ----------------------------
        # ZMQ (1포트, JSON only)
        # ----------------------------
        self.zmq_thread = ZmqRecvThread(PULL_CONNECT1, parent=self)
        self.zmq_thread.text_ready.connect(self._on_zmq_text)
        self.zmq_thread.start()

        # ----------------------------
        # RTSP threads (실시간 표시 X, 프레임만 업데이트)
        # ----------------------------
        self.rtspCAM1 = RtspThread(RTSP_CAM_IP, name="CAM1", parent=self)
        self.rtspCAM1.frame_ready.connect(lambda q, b: self._on_frame("cam1", self.image_1, q, b))
        self.rtspCAM1.start()

        self.rtspWS1 = RtspThread(RTSP_A1_IP, name="WS1", parent=self)
        self.rtspWS1.frame_ready.connect(lambda q, b: self._on_frame("ws1", self.image_2, q, b))
        self.rtspWS1.start()

        self.rtspDS1 = RtspThread(RTSP_B1_IP, name="DS1", parent=self)
        self.rtspDS1.frame_ready.connect(lambda q, b: self._on_frame("ds1", self.image_3, q, b))
        self.rtspDS1.start()

        self.rtspWS2 = RtspThread(RTSP_A2_IP, name="WS2", parent=self)
        self.rtspWS2.frame_ready.connect(lambda q, b: self._on_frame("ws2", self.image_4, q, b))
        self.rtspWS2.start()

        self.rtspDS2 = RtspThread(RTSP_B2_IP, name="DS2", parent=self)
        self.rtspDS2.frame_ready.connect(lambda q, b: self._on_frame("ds2", self.image_5, q, b))
        self.rtspDS2.start()

        self.rtspWheelWS = RtspThread(RTSP_C1_IP, name="Wheel_WS", parent=self)
        self.rtspWheelWS.frame_ready.connect(lambda q, b: self._on_frame("wheel_ws", self.image_6, q, b))
        self.rtspWheelWS.start()

        self.rtspWheelDS = RtspThread(RTSP_C2_IP, name="Wheel_DS", parent=self)
        self.rtspWheelDS.frame_ready.connect(lambda q, b: self._on_frame("wheel_ds", self.image_7, q, b))
        self.rtspWheelDS.start()

        # ----------------------------
        # CRY threads (dB)
        # ----------------------------
        self.cry_ws1 = CryApiThread(
            ip=CRY_A1_IP, port=CRY_A1_PORT, user=CRY_USER, pw=CRY_PW,
            use_https=CRY_A1_USE_HTTPS,
            interval_sec=CRY_INTERVAL_SEC, timeout_sec=CRY_TIMEOUT_SEC,
            parent=self
        )
        self.cry_ws1.db_ready.connect(lambda v: self._on_db("ws1", v, self.msg_2))
        self.cry_ws1.start()

        self.cry_ds1 = CryApiThread(
            ip=CRY_B1_IP, port=CRY_B1_PORT, user=CRY_USER, pw=CRY_PW,
            use_https=CRY_B1_USE_HTTPS,
            interval_sec=CRY_INTERVAL_SEC, timeout_sec=CRY_TIMEOUT_SEC,
            parent=self
        )
        self.cry_ds1.db_ready.connect(lambda v: self._on_db("ds1", v, self.msg_3))
        self.cry_ds1.start()

        self.cry_ws2 = CryApiThread(
            ip=CRY_A2_IP, port=CRY_A2_PORT, user=CRY_USER, pw=CRY_PW,
            use_https=CRY_A2_USE_HTTPS,
            interval_sec=CRY_INTERVAL_SEC, timeout_sec=CRY_TIMEOUT_SEC,
            parent=self
        )
        self.cry_ws2.db_ready.connect(lambda v: self._on_db("ws2", v, self.msg_6))
        self.cry_ws2.start()

        self.cry_ds2 = CryApiThread(
            ip=CRY_B2_IP, port=CRY_B2_PORT, user=CRY_USER, pw=CRY_PW,
            use_https=CRY_B2_USE_HTTPS,
            interval_sec=CRY_INTERVAL_SEC, timeout_sec=CRY_TIMEOUT_SEC,
            parent=self
        )
        self.cry_ds2.db_ready.connect(lambda v: self._on_db("ds2", v, self.msg_5))
        self.cry_ds2.start()

    # ---------------- UI helpers ----------------
    def _set_msg_1(self, text):
        self.msg_1.setText(str(text))

    def _safe_set_label_path(self, label, path):
        if not path:
            return
        try:
            pm = QPixmap(path)
            if pm.isNull():
                return
            set_label_pixmap_fill(label, pm)
        except Exception:
            pass

    # ---------------- frames ----------------
    def _on_frame(self, cam_id, label, qimg, bgr):
        # 실시간 표시를 끔(썸네일은 final 시점에만 표시)
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

        # 여러 줄로 붙어 올 가능성 방어
        lines = []
        if "\n" in s:
            for ln in s.splitlines():
                ln = ln.strip()
                if ln:
                    lines.append(ln)
        else:
            lines = [s]

        for one in lines:
            try:
                data = json.loads(one)
            except Exception:
                continue

            mtype = str(data.get("type", "")).strip()

            # 1) car_event
            if mtype == "car_event":
                self.wagon_ctrl.on_car_event(data)
                continue

            # 2) wheel_event / car_update
            if mtype in ("wheel_event", "car_update"):
                self._handle_wheel_like_event(data)
                continue

    def _handle_wheel_like_event(self, data):
        pos = str(data.get("pos", "")).strip().upper()
        event_id = data.get("event_id")
        if not event_id:
            return
        event_id = str(event_id).strip()

        # car_no
        car_no = data.get("wheel_car_no")
        if car_no is None:
            car_no = data.get("car_no")
        car_no_str = str(car_no).strip() if car_no is not None else ""

        # 값 추출 (wheel_event: flat / car_update: nested)
        if data.get("type") == "wheel_event":
            w1_rot = data.get("wheel_1st_rotation", 0)
            w1_pos = data.get("wheel_1st_position", 0)
            w2_rot = data.get("wheel_2nd_rotation", 0)
            w2_pos = data.get("wheel_2nd_position", 0)
        else:
            wheel = data.get("wheel", {})
            if wheel is None or not isinstance(wheel, dict):
                wheel = {}
            w1_rot = wheel.get("wheel_1st_rotation", 0)
            w1_pos = wheel.get("wheel_1st_position", 0)
            w2_rot = wheel.get("wheel_2nd_rotation", 0)
            w2_pos = wheel.get("wheel_2nd_position", 0)

        status_1st = judge_one_wheel(w1_rot, w1_pos)
        status_2nd = judge_one_wheel(w2_rot, w2_pos)

        # 라벨 표시(원하면 꺼도 됨)
        if pos == "WS":
            self.msg_4.setText("1st:{0}".format(status_1st))
            self.msg_8.setText("2nd:{0}".format(status_2nd))
        elif pos == "DS":
            self.msg_7.setText("1st:{0}".format(status_1st))
            self.msg_9.setText("2nd:{0}".format(status_2nd))

        # wagon_controller에 wheel 상태 전달 (stage1 조건 체크)
        self.wagon_ctrl.on_wheel_status(
            event_id=event_id,
            pos=pos,
            status_1st=status_1st,
            status_2nd=status_2nd,
            car_no_str=car_no_str
        )

    # ---------------- stage1: DB 1차 저장 ----------------
    def _on_stage1_ready(self, rec):
        # stage1은 HMI 표시 X, DB insert만
        # (db_writer가 insert를 담당)
        item = dict(rec)

        # ts 처리: 문자열이면 datetime으로 변환 시도
        ts = item.get("ts")
        if isinstance(ts, str):
            try:
                item["ts"] = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            except Exception:
                item["ts"] = datetime.now()

        self.db_writer.enqueue(item)

    # ---------------- final: 2구간 포함 완성 ----------------
    def _on_final_ready(self, rec):
        car_no_str = str(rec.get("car_no", "")).strip()
        label_text = "N" if car_no_str == "none" else car_no_str

        # 1) 테이블 insert (final에서만)
        self.table_manager.insert_record(rec)

        # 2) 휠 상태 테이블 반영
        self.table_manager.update_wheel_status(car_no_str, "WS", rec.get("ws_wheel1_status", ""), rec.get("ws_wheel2_status", ""))
        self.table_manager.update_wheel_status(car_no_str, "DS", rec.get("ds_wheel1_status", ""), rec.get("ds_wheel2_status", ""))

        # 3) 버튼색/상태
        max_db = max(
            float(rec.get("ws1_db", 0.0)),
            float(rec.get("ds1_db", 0.0)),
            float(rec.get("ws2_db", 0.0)),
            float(rec.get("ds2_db", 0.0)),
        )
        overall = rec.get("wheel_overall", "")
        self.button_manager.push_front(label_text, max_db, overall)

        # 4) DB: (stage1 insert 후) 2구간 update는 다음 파일(db_writer)에서 처리하도록 예정
        # 지금은 안전하게 "완성본"도 enqueue (db_writer가 insert만이면 중복될 수 있으니,
        # 다음 단계에서 db_writer를 update 지원으로 바꾸면 여기서 update로 바꿀 것)
        item = dict(rec)
        ts = item.get("ts")
        if isinstance(ts, str):
            try:
                item["ts"] = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            except Exception:
                item["ts"] = datetime.now()

        self.db_writer.enqueue(item)

        # 5) 썸네일(저장된 이미지) 표시
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
        left = self.wagon_ctrl.flush_remaining_records()
        for rec in left:
            try:
                self.db_writer.enqueue(rec)
            except Exception:
                pass

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
