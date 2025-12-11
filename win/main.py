#main.py
import os
import sys
import subprocess
from datetime import datetime
import re

from PyQt5 import uic, QtWidgets
from PyQt5.QtWidgets import (
    QMainWindow, QPushButton, QTableWidgetItem, QApplication
)
from PyQt5.QtCore import Qt, QCoreApplication, QTimer
from PyQt5.QtGui import QPixmap, QColor

from config.config import (
    DB_HOST, DB_PORT, DB_USER, DB_PW,
    CRY_USER, CRY_PW,
    CRY_A1_IP, CRY_A1_PORT, CRY_A1_USE_HTTPS,
    CRY_B1_IP, CRY_B1_PORT, CRY_B1_USE_HTTPS,
    CRY_A2_IP, CRY_A2_PORT, CRY_A2_USE_HTTPS,
    CRY_B2_IP, CRY_B2_PORT, CRY_B2_USE_HTTPS,
    CRY_INTERVAL_SEC, CRY_TIMEOUT_SEC,
    PULL_CONNECT1, PULL_CONNECT2, PULL_CONNECT3, 
    RTSP_A1_IP, RTSP_B1_IP, RTSP_C1_IP,
    RTSP_A2_IP, RTSP_B2_IP, RTSP_C2_IP,
)

from utils.thresholds_utils import load_thresholds_from_json, save_thresholds_to_json
from utils.image_utils import (
    set_label_pixmap_fill, ws_car1_path,
    ws_leak1_path, ds_leak1_path,
    ws_leak2_path, ds_leak2_path,
    ws_wheel1_path, ds_wheel1_path,
    save_bgr_image_to_file
)
from utils.db_writer import DbWriterThread

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_PATH = os.path.join(BASE_DIR, "ui", "window_hmi3.ui")
USE_DUMMY_CRY = True 
USE_DUMMY_CAMERA = True

if USE_DUMMY_CAMERA:
    from test.zmq_rtsp_test import ZmqRecvThread, RtspThread
else:
    from workers.threads_zmq_rtsp import ZmqRecvThread, RtspThread

if USE_DUMMY_CRY:
    from test.cry_api_test import CryApiThread
else:
    from api.cry_api import CryApiThread


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        uic.loadUi(UI_PATH, self)

        # ============================================================
        # DB writer
        # ============================================================
        self.db_writer = DbWriterThread(DB_HOST, DB_PORT, DB_USER, DB_PW, parent=self)
        self.db_writer.start()

        # ============================================================
        # 버튼 수집
        # ============================================================
        self.paint_buttons = []
        i = 1
        while True:
            btn = self.findChild(QPushButton, f"N_{i}")
            if btn is None:
                break
            self.paint_buttons.append(btn)
            i += 1

        for btn in self.paint_buttons:
            btn.clicked.connect(lambda _, b=btn: self._open_viewer_for_button(b))

        self.button_labels = [""] * len(self.paint_buttons)
        self.button_db_values = [None] * len(self.paint_buttons)

        # ============================================================
        # 상태 변수
        # ============================================================
        self.current_label = None   # 현재 대차 번호 ("none" 또는 3자리 숫자)

        # 1번 구간 START~END 플래그 + cam1 캡쳐 예약 여부
        self.in_wagon = False
        self.cam1_pending_capture = False


        # cam1 이미지 경로
        self.current_cam1_path = ""

        # 1번 구간 피크 변수 (WS1/DS1)
        self.current_peak_db_ws1 = None
        self.current_peak_db_ds1 = None
        self.peak_ws1_bgr = None
        self.peak_ds1_bgr = None

        # 2번 구간 피크 변수 (WS2/DS2)
        self.current_peak_db_ws2 = None
        self.current_peak_db_ds2 = None
        self.peak_ws2_bgr = None
        self.peak_ds2_bgr = None

        # 최신 실시간 프레임
        self.latest_frame_cam1_bgr = None
        self.latest_frame_ws1_bgr = None
        self.latest_frame_ds1_bgr = None
        self.latest_frame_ws2_bgr = None
        self.latest_frame_ds2_bgr = None
        self.latest_frame_wheel1_bgr = None

        # 대차 큐 (1번 구간 완료된 대차들이 쌓임)
        self.car_queue = []
        self.delay_count = 2   # 7대차 뒤에서 WS2/DS2를 붙임

        # ============================================================
        # 임계값
        # ============================================================
        self.thresholds = load_thresholds_from_json()
        self.lineEdit_2.setText(str(self.thresholds["strong"]))
        self.lineEdit_3.setText(str(self.thresholds["mid"]))
        self.lineEdit_4.setText(str(self.thresholds["weak"]))

        self.pushButton_2.clicked.connect(self.button_repaint)

        # ============================================================
        # 테이블 설정 (WS1/DS1/WS2/DS2/휠)
        # ============================================================
        self.tableWidget.setColumnCount(7)
        self.tableWidget.setHorizontalHeaderLabels(["대차", "WS1", "DS1", "WS2", "DS2", "WS휠","DS휠"])
        self.tableWidget.verticalHeader().setVisible(False)
        self.tableWidget.setEditTriggers(self.tableWidget.NoEditTriggers)
        self.tableWidget.setSelectionBehavior(self.tableWidget.SelectRows)
        self.tableWidget.setSelectionMode(self.tableWidget.SingleSelection)
        header = self.tableWidget.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        self.max_table_rows = 172

        # ============================================================
        # ZMQ (cam1)
        # ============================================================
        self.zmq_thread = ZmqRecvThread(PULL_CONNECT1, parent=self)
        self.zmq_thread.frame_ready.connect(self.update_ui_cam)
        self.zmq_thread.start()

        self.zmq_thread2 = ZmqRecvThread(PULL_CONNECT2, parent=self)
        self.zmq_thread2.frame_ready.connect(self.update_ui_cam2)
        self.zmq_thread2.start()


        # ============================================================
        # RTSP threads
        # ============================================================
        self.rtspA1 = RtspThread(RTSP_A1_IP, name="WS1", parent=self)
        self.rtspA1.frame_ready.connect(self.update_ws1_frame)
        self.rtspA1.start()

        self.rtspB1 = RtspThread(RTSP_B1_IP, name="DS1", parent=self)
        self.rtspB1.frame_ready.connect(self.update_ds1_frame)
        self.rtspB1.start()

        self.rtspA2 = RtspThread(RTSP_A2_IP, name="WS2", parent=self)
        self.rtspA2.frame_ready.connect(self.update_ws2_frame)
        self.rtspA2.start()

        self.rtspB2 = RtspThread(RTSP_B2_IP, name="DS2", parent=self)
        self.rtspB2.frame_ready.connect(self.update_ds2_frame)
        self.rtspB2.start()

        # self.rtspC1 = RtspThread(RTSP_C1_IP, name="Wheel1", parent=self)
        # self.rtspC1.frame_ready.connect(self.update_wheel1_frame)
        # self.rtspC1.start()

        # ============================================================
        # CRY dB threads — WS1/DS1/WS2/DS2 각각 따로
        # ============================================================
        # WS1
        self.cry_ws1 = CryApiThread(
            ip=CRY_A1_IP, port=CRY_A1_PORT, user=CRY_USER, pw=CRY_PW,
            use_https=CRY_A1_USE_HTTPS,
            interval_sec=CRY_INTERVAL_SEC, timeout_sec=CRY_TIMEOUT_SEC,
            parent=self
        )
        self.cry_ws1.db_ready.connect(self.update_ws1_db)
        self.cry_ws1.start()

        # DS1
        self.cry_ds1 = CryApiThread(
            ip=CRY_B1_IP, port=CRY_B1_PORT, user=CRY_USER, pw=CRY_PW,
            use_https=CRY_B1_USE_HTTPS,
            interval_sec=CRY_INTERVAL_SEC, timeout_sec=CRY_TIMEOUT_SEC,
            parent=self
        )
        self.cry_ds1.db_ready.connect(self.update_ds1_db)
        self.cry_ds1.start()

        # WS2
        self.cry_ws2 = CryApiThread(
            ip=CRY_A2_IP, port=CRY_A2_PORT, user=CRY_USER, pw=CRY_PW,
            use_https=CRY_A2_USE_HTTPS,
            interval_sec=CRY_INTERVAL_SEC, timeout_sec=CRY_TIMEOUT_SEC,
            parent=self
        )
        self.cry_ws2.db_ready.connect(self.update_ws2_db)
        self.cry_ws2.start()

        # DS2
        self.cry_ds2 = CryApiThread(
            ip=CRY_B2_IP, port=CRY_B2_PORT, user=CRY_USER, pw=CRY_PW,
            use_https=CRY_B2_USE_HTTPS,
            interval_sec=CRY_INTERVAL_SEC, timeout_sec=CRY_TIMEOUT_SEC,
            parent=self
        )
        self.cry_ds2.db_ready.connect(self.update_ds2_db)
        self.cry_ds2.start()

    # ============================================================
    # 버튼 → 조회프로그램(viewer.py) 실행
    # ============================================================
    def _open_viewer_for_button(self, btn):
        raw = (btn.text() or "").strip()

        if not raw:
            QtWidgets.QMessageBox.information(self, "안내", "버튼에 대차번호가 없습니다.")
            return

        if raw == "N":
            car_no = "none"
        else:
            m = re.search(r"\b(\d{3})\b", raw)
            car_no = m.group(1) if m else raw

        if (not car_no) or (car_no != "none" and not car_no.isdigit()):
            QtWidgets.QMessageBox.information(self, "안내", "버튼에 대차번호가 없습니다.")
            return

        self._launch_viewer_process(car_no)

    def _launch_viewer_process(self, car_no: str):
        viewer_py = os.path.join(os.path.dirname(__file__), "viewer.py")
        if not os.path.exists(viewer_py):
            QtWidgets.QMessageBox.critical(
                self, "오류",
                f"viewer.py 파일을 찾을 수 없습니다.\n{viewer_py}"
            )
            return

        try:
            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

            subprocess.Popen(
                [sys.executable, viewer_py, car_no],
                creationflags=creationflags
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "실행 오류",
                f"조회 프로그램 실행 실패:\n{e}"
            )

    # ================================================================
    # 프레임 업데이트
    # ================================================================
    def update_ws1_frame(self, qimg, bgr):
        set_label_pixmap_fill(self.image_2, QPixmap.fromImage(qimg))
        self.latest_frame_ws1_bgr = bgr

    def update_ds1_frame(self, qimg, bgr):
        set_label_pixmap_fill(self.image_3, QPixmap.fromImage(qimg))
        self.latest_frame_ds1_bgr = bgr

    def update_ws2_frame(self, qimg, bgr):
        set_label_pixmap_fill(self.image_4, QPixmap.fromImage(qimg))
        self.latest_frame_ws2_bgr = bgr

    def update_ds2_frame(self, qimg, bgr):
        set_label_pixmap_fill(self.image_5, QPixmap.fromImage(qimg))
        self.latest_frame_ds2_bgr = bgr

    # def update_wheel1_frame(self, qimg, bgr):
    #     set_label_pixmap_fill(self.image_6, QPixmap.fromImage(qimg))
    #     self.latest_frame_wheel1_bgr = bgr

    # ================================================================
    # CRY dB 업데이트 (WS1 / DS1 / WS2 / DS2)
    # ================================================================
    def update_ws1_db(self, db_value: float):
        try:
            v = float(db_value)
        except:
            v = 0.0
        self.msg_2.setText(str(round(v, 2)))  # WS1 dB UI

        # 1번 구간: START~END(in_wagon) 동안만 피크 홀드
        if self.in_wagon:
            if (self.current_peak_db_ws1 is None) or (v > self.current_peak_db_ws1):
                self.current_peak_db_ws1 = v
                if self.latest_frame_ws1_bgr is not None:
                    self.peak_ws1_bgr = self.latest_frame_ws1_bgr.copy()

    def update_ds1_db(self, db_value: float):
        try:
            v = float(db_value)
        except:
            v = 0.0
        self.msg_3.setText(str(round(v, 2)))  # DS1 dB UI

        if self.in_wagon:
            if (self.current_peak_db_ds1 is None) or (v > self.current_peak_db_ds1):
                self.current_peak_db_ds1 = v
                if self.latest_frame_ds1_bgr is not None:
                    self.peak_ds1_bgr = self.latest_frame_ds1_bgr.copy()

    def update_ws2_db(self, db_value: float):
        try:
            v = float(db_value)
        except:
            v = 0.0
        self.msg_6.setText(str(round(v, 2)))  # WS2 dB UI

        if self.in_wagon and len(self.car_queue) >= (self.delay_count - 1):
            if (self.current_peak_db_ws2 is None) or (v > self.current_peak_db_ws2):
                self.current_peak_db_ws2 = v
                if self.latest_frame_ws2_bgr is not None:
                    self.peak_ws2_bgr = self.latest_frame_ws2_bgr.copy()

    def update_ds2_db(self, db_value: float):
        try:
            v = float(db_value)
        except:
            v = 0.0
        self.msg_5.setText(str(round(v, 2)))  # DS2 dB UI

        if self.in_wagon and len(self.car_queue) >= (self.delay_count - 1):
            if (self.current_peak_db_ds2 is None) or (v > self.current_peak_db_ds2):
                self.current_peak_db_ds2 = v
                if self.latest_frame_ds2_bgr is not None:
                    self.peak_ds2_bgr = self.latest_frame_ds2_bgr.copy()

    # ================================================================
    # ZMQ (AI 번호 + cam1) - START/END 신호 처리
    # ================================================================
    def update_ui_cam(self, qimg, bgr, text):
        # cam1 실시간 영상 표시
        set_label_pixmap_fill(self.image_1, QPixmap.fromImage(qimg))
        self.latest_frame_cam1_bgr = bgr

        # 문자열 정리
        raw = ""
        if isinstance(text, str):
            raw = text.strip()

        # 코드가 아예 없으면: 영상만 갱신(번호는 유지)
        if not raw:
            return

        # START 신호: 1번 구간 시작
        if raw == "START":
            self._on_wagon_start()
            return

        # END 신호: "NONE" 또는 3자리 숫자
        if raw == "NONE" or re.fullmatch(r"\d{3}", raw):
            self._on_wagon_end(raw)
            return

        # 혹시 다른 형식으로 3자리 숫자가 섞여 있는 경우
        m = re.search(r"\b(\d{3})\b", raw)
        if m:
            self._on_wagon_end(m.group(1))
            return

        # 그 외 텍스트는 무시
        return
    
    def update_ui_cam2(self, qimg, bgr, text):
        # cam2 실시간 영상 표시
        set_label_pixmap_fill(self.image_6, QPixmap.fromImage(qimg))

        # 필요하면 나중에 저장/캡쳐 쓸 수 있게 보관
        self.latest_frame_cam2_bgr = bgr

        # text는 JSON 문자열이라고 했으니까 일단 그대로 보여줌
        if isinstance(text, str):
            self.msg_4.setText(text)
            print(text)
        else:
            # 혹시 bytes나 다른 타입으로 들어올 수도 있으니 방어
            try:
                self.msg_4.setText(str(text))
            except Exception:
                self.msg_4.setText("")

    # ================================================================
    # START / END 처리 (1번 구간)
    # ================================================================
    def _on_wagon_start(self):
        """리눅스에서 START 신호가 들어왔을 때 호출 (1번 구간 시작)"""
        self.in_wagon = True
        self.cam1_pending_capture = True

        # 아직 번호는 모름
        self.msg_1.setText("...")

        # 1번 구간 피크 초기화
        self.current_peak_db_ws1 = None
        self.current_peak_db_ds1 = None
        self.peak_ws1_bgr = None
        self.peak_ds1_bgr = None

        # cam1 이미지는 START + 1초 뒤에 캡쳐
        #QTimer.singleShot(1000, self._capture_cam1_after_start)
        self._capture_cam1_after_start()

    def _capture_cam1_after_start(self):
        """START 후 1초 뒤에 cam1 프레임을 파일로 저장"""
        if not self.cam1_pending_capture:
            return
        if self.latest_frame_cam1_bgr is None:
            return

        ts = datetime.now()
        car_no_for_path = self.current_label if self.current_label else "none"

        path1 = ws_car1_path(ts, car_no_for_path)
        if save_bgr_image_to_file(self.latest_frame_cam1_bgr, path1):
            self.current_cam1_path = path1

        self.cam1_pending_capture = False

    def _on_wagon_end(self, raw_code: str):
        """
        리눅스에서 END 신호가 들어왔을 때 호출
        raw_code: "NONE" 또는 "123" 같은 3자리 문자열
        """
        # START 없이 END가 들어온 경우 방어
        if not self.in_wagon:
            if raw_code == "NONE":
                self.msg_1.setText("N")
                self.current_label = "none"
            else:
                self.msg_1.setText(raw_code)
                self.current_label = raw_code
            return
        
        # 번호 해석
        if raw_code == "NONE":
            car_no = "none"
            display_label = "N"
        else:
            car_no = raw_code
            display_label = car_no

        # 화면 표시
        self.msg_1.setText(display_label)
        self.current_label = car_no

        # cam1 캡쳐 예약이 남아 있으면 여기서라도 한 번 시도
        if self.cam1_pending_capture:
            self._capture_cam1_after_start()
            self.cam1_pending_capture = False

        # 1번 구간 데이터(WS1/DS1 + cam1)를 큐에 넣고
        # 필요하면 2번 구간(WS2/DS2)까지 붙여서 UI/DB 반영
        self._push_current_record_to_queue()
        self._queue_push()

        # 1번 구간 종료
        self.in_wagon = False
        self._reset_for_new_car()

    # ================================================================
    # 새 대차 초기화 (1번 구간만 리셋)
    # ================================================================
    def _reset_for_new_car(self):
        self.current_cam1_path = ""

        self.current_peak_db_ws1 = None
        self.current_peak_db_ds1 = None
        self.peak_ws1_bgr = None
        self.peak_ds1_bgr = None
        # WS2/DS2는 _queue_push()에서 pop될 때마다 리셋

    # ================================================================
    # 대차 레코드 생성 → 큐에 push (1번 구간 데이터만)
    # ================================================================
    def _push_current_record_to_queue(self):
        car_no = self.current_label or ""
        ts = datetime.now()

        rec = {
            "ts": ts,
            "car_no": car_no,

            "img_cam1_path": self.current_cam1_path or "",

            # 1번 구간
            "ws1_db": float(self.current_peak_db_ws1 or 0.0),
            "ds1_db": float(self.current_peak_db_ds1 or 0.0),

            "img_ws1_path": "",
            "img_ds1_path": "",

            # 2번 구간 (처음엔 0, 나중에 _queue_push에서 채움)
            "ws2_db": 0.0,
            "ds2_db": 0.0,

            "img_ws2_path": "",
            "img_ds2_path": "",

            # 기존 DBWriter 호환
            "dba": float(self.current_peak_db_ws1 or 0.0),
            "dbb": float(self.current_peak_db_ds1 or 0.0),
            "img_a_path": "",
            "img_b_path": "",
        }

        # 1번 구간 WS1 이미지
        if self.peak_ws1_bgr is not None:
            pathA = ws_leak1_path(ts, car_no)
            if save_bgr_image_to_file(self.peak_ws1_bgr, pathA):
                rec["img_ws1_path"] = pathA
                rec["img_a_path"] = pathA

        # 1번 구간 DS1 이미지
        if self.peak_ds1_bgr is not None:
            pathB = ds_leak1_path(ts, car_no)
            if save_bgr_image_to_file(self.peak_ds1_bgr, pathB):
                rec["img_ds1_path"] = pathB
                rec["img_b_path"] = pathB

        self.car_queue.append(rec)

    # ================================================================
    # 큐 pop → WS2/DS2 붙이기 → UI/DB 반영
    # ================================================================
    def _queue_push(self):
        while len(self.car_queue) >= self.delay_count:
            rec = self.car_queue.pop(0)

            car_no = rec["car_no"]
            ts = datetime.now()

            # 2번 구간 WS2 이미지
            if self.peak_ws2_bgr is not None:
                pathA = ws_leak2_path(ts, car_no)
                if save_bgr_image_to_file(self.peak_ws2_bgr, pathA):
                    rec["img_ws2_path"] = pathA

            # 2번 구간 DS2 이미지
            if self.peak_ds2_bgr is not None:
                pathB = ds_leak2_path(ts, car_no)
                if save_bgr_image_to_file(self.peak_ds2_bgr, pathB):
                    rec["img_ds2_path"] = pathB

            # 2번 구간 dB 붙이기 (큐에서 pop되는 시점까지의 피크)
            rec["ws2_db"] = float(self.current_peak_db_ws2 or 0.0)
            rec["ds2_db"] = float(self.current_peak_db_ds2 or 0.0)

            # UI/DB 반영
            self._apply_record_to_ui_and_db(rec)

            # 다음 대차를 위한 2번 구간 피크 리셋
            self.current_peak_db_ws2 = None
            self.current_peak_db_ds2 = None
            self.peak_ws2_bgr = None
            self.peak_ds2_bgr = None

    # ================================================================
    # UI/DB 반영
    # ================================================================
    def _apply_record_to_ui_and_db(self, rec: dict):
        car_no = rec["car_no"]

        # 버튼에는 'none' 대신 'N' 문자열로 표시
        label_text = "N" if car_no == "none" else car_no
        self._push_front_buttons(label_text, rec["ws1_db"])

        # 테이블 한 줄 추가
        self._table_insert_new(rec)

        # DB에는 car_no='none' 그대로 저장
        self.db_writer.enqueue(rec)

    # ================================================================
    # 테이블
    # ================================================================
    def _table_insert_new(self, rec):
        row = 0
        self.tableWidget.insertRow(row)

        def setcol(c, text, dbv=None):
            it = QTableWidgetItem(text)
            self.tableWidget.setItem(row, c, it)
            if dbv is not None:
                it.setBackground(QColor(self._color_for_db(dbv)))
            it.setForeground(QColor("black"))

        car_no = rec["car_no"]

        setcol(0, str(car_no))
        setcol(1, f"{rec['ws1_db']:.2f}", rec["ws1_db"])
        setcol(2, f"{rec['ds1_db']:.2f}", rec["ds1_db"])
        setcol(3, f"{rec['ws2_db']:.2f}", rec["ws2_db"])
        setcol(4, f"{rec['ds2_db']:.2f}", rec["ds2_db"])
        setcol(5, "")  # Wheel 상태 (나중에 확장)

        if self.tableWidget.rowCount() > self.max_table_rows:
            self.tableWidget.removeRow(self.tableWidget.rowCount() - 1)

    def _repaint_table(self):
        rows = self.tableWidget.rowCount()
        for r in range(rows):
            for c in range(1, 5):  # ws1, ds1, ws2, ds2
                item = self.tableWidget.item(r, c)
                if item is None:
                    continue
                text = item.text().strip()
                if not text:
                    continue
                try:
                    v = float(text)
                except Exception:
                    continue
                color_hex = self._color_for_db(v)
                item.setBackground(QColor(color_hex))
                item.setForeground(QColor("black"))

    # ================================================================
    # 버튼 색
    # ================================================================
    def _color_for_db(self, db_value):
        if db_value is None:
            return "#FFFFFF"
        t = self.thresholds
        if db_value < t["weak"]:
            return "#67E467"
        elif db_value < t["mid"]:
            return "#4A89E9"
        elif db_value < t["strong"]:
            return "#E7E55F"
        else:
            return "#EB5E5E"

    def _push_front_buttons(self, label_text, db_value):
        self.button_labels.insert(0, str(label_text))
        self.button_db_values.insert(0, db_value)
        self.button_labels = self.button_labels[:len(self.paint_buttons)]
        self.button_db_values = self.button_db_values[:len(self.paint_buttons)]
        self._repaint_all_buttons()

    def _repaint_all_buttons(self):
        for i, btn in enumerate(self.paint_buttons):
            lbl = self.button_labels[i]
            dbv = self.button_db_values[i]

            btn.setText(lbl)
            color = self._color_for_db(dbv)

            if color.upper() == "#FFFFFF":
                btn.setStyleSheet("background-color: #FFFFFF; color: black;")
            else:
                btn.setStyleSheet(f"background-color: {color}; color: black;")

    # ================================================================
    # 임계값 재정렬
    # ================================================================
    def button_repaint(self):
        def _safe_float(le, d):
            try:
                return float(le.text())
            except:
                return d

        strong = _safe_float(self.lineEdit_2, self.thresholds.get("strong", 5.0))
        mid    = _safe_float(self.lineEdit_3, self.thresholds.get("mid", 4.0))
        weak   = _safe_float(self.lineEdit_4, self.thresholds.get("weak", 3.0))

        vals = sorted([weak, mid, strong])
        self.thresholds["weak"]  = vals[0]
        self.thresholds["mid"]   = vals[1]
        self.thresholds["strong"]= vals[2]

        save_thresholds_to_json(self.thresholds)
        self._repaint_all_buttons()
        self._repaint_table()

    # ================================================================
    # 종료 처리
    # ================================================================
    def closeEvent(self, event):
        if self.current_label is not None:
            self._push_current_record_to_queue()

        while self.car_queue:
            rec = self.car_queue.pop(0)
            self.db_writer.enqueue(rec)

        for w in [
            self.zmq_thread,
            self.zmq_thread2,
            self.rtspA1, self.rtspB1, self.rtspA2, self.rtspB2,
            self.cry_ws1, self.cry_ds1, self.cry_ws2, self.cry_ds2
        ]:
            try:
                w.stop()
                w.wait(2000)
            except:
                pass

        self.db_writer.stop()
        self.db_writer.wait(3000)

        event.accept()


if __name__ == "__main__":
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
