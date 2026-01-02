# viewer.py  (조회 프로그램 - posco.data / car_no + 날짜(또는 none 전체) 조회)
# -*- coding:utf-8 -*-
import sys
import os

import pymysql
from datetime import datetime
from PyQt5 import uic
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QListWidgetItem, QMessageBox,
    QToolBar, QLineEdit, QPushButton, QWidgetAction
)
from PyQt5.QtGui import QPixmap, QColor
from PyQt5.QtCore import Qt

from utils.color_json_utils import load_thresholds_from_json, save_thresholds_to_json

# 작업 디렉토리 고정
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ==== DB 접속 정보 ====
DB_HOST = "127.0.0.1"
DB_USER = "root"
DB_PASSWORD = "0000"
DB_NAME = "posco"
TABLE_NAME = "data"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_PATH = os.path.join(BASE_DIR, "ui", "window_check.ui")


class WindowClass(QMainWindow):
    def __init__(self, car_no: str = ""):
        super().__init__()
        uic.loadUi(UI_PATH, self)

        # 이미지 라벨 기본 설정 (image_1~7)
        for name in ("image_1", "image_2", "image_3", "image_4", "image_5", "image_6", "image_7"):
            if hasattr(self, name):
                w = getattr(self, name)
                w.setAlignment(Qt.AlignCenter)
                w.setScaledContents(True)

        # 임계값 로드 (HMI와 동일 JSON)
        self.thresholds = load_thresholds_from_json()
        self.v_strong = float(self.thresholds.get("strong", 5.0))
        self.v_mid    = float(self.thresholds.get("mid", 4.0))
        self.v_weak   = float(self.thresholds.get("weak", 3.0))
        self.v_min    = float(self.thresholds.get("min", 0.0))

        if hasattr(self, "lineEdit_2"):
            self.lineEdit_2.setText(str(self.v_strong))
        if hasattr(self, "lineEdit_3"):
            self.lineEdit_3.setText(str(self.v_mid))
        if hasattr(self, "lineEdit_4"):
            self.lineEdit_4.setText(str(self.v_weak))
        if hasattr(self, "lineEdit_5"):
            self.lineEdit_5.setText(str(self.v_min))

        # 날짜 선택 툴바
        self._build_date_toolbar()

        # 상태
        self.conn = None
        self.car_no = (car_no or "").strip()   # '203' 또는 'none'
        self._rows_cache = []

        self._wire_events()
        self._connect_db()

        # 초기 로드:
        if self.car_no != "none":
            default_date = datetime.now().strftime("%Y%m%d")
            self.le_date.setText(default_date)

        self._reload_from_date()

    # ─────────────────────────────────────
    # UI 구성 / 이벤트 연결
    # ─────────────────────────────────────
    def _build_date_toolbar(self):
        tb = QToolBar("날짜 선택", self)
        self.addToolBar(Qt.TopToolBarArea, tb)
        tb.setMovable(False)

        self.le_date = QLineEdit(self)
        self.le_date.setMaxLength(8)
        self.le_date.setPlaceholderText("YYYYMMDD")
        self.le_date.setStyleSheet("background:white; color:black;")

        self.btn_load = QPushButton("불러오기", self)
        self.btn_load.setStyleSheet("background:white; color:black;")
        self.btn_load.clicked.connect(self._reload_from_date)

        act_le = QWidgetAction(self)
        act_le.setDefaultWidget(self.le_date)
        tb.addAction(act_le)

        act_bt = QWidgetAction(self)
        act_bt.setDefaultWidget(self.btn_load)
        tb.addAction(act_bt)

    def _wire_events(self):
        if hasattr(self, "listWidget"):
            self.listWidget.itemClicked.connect(self._on_item_clicked)

        if hasattr(self, "pushButton_2"):
            self.pushButton_2.clicked.connect(self._on_threshold_save_clicked)

    def closeEvent(self, e):
        try:
            if self.conn:
                self.conn.close()
        except Exception:
            pass
        e.accept()

    # ─────────────────────────────────────
    # DB 연결/조회
    # ─────────────────────────────────────
    def _connect_db(self):
        try:
            self.conn = pymysql.connect(
                host=DB_HOST,
                user=DB_USER,
                password=DB_PASSWORD,
                database=DB_NAME,
                charset="utf8mb4",
                autocommit=True,
            )
        except Exception as e:
            QMessageBox.critical(self, "DB 연결 실패", f"DB({DB_NAME}) 연결 실패\n\n{e}")
            self.conn = None

    def _reload_from_date(self):
        if not self.conn:
            return

        if not self.car_no:
            QMessageBox.information(self, "안내", "대차번호가 없습니다.")
            return

        if self.car_no == "none":
            self._load_list(date_filter=None)
            return

        date_str = self.le_date.text().strip()
        if not (len(date_str) == 8 and date_str.isdigit()):
            QMessageBox.information(self, "안내", "날짜는 YYYYMMDD(8자리 숫자)로 입력하세요.")
            return

        self._load_list(date_filter=date_str)

    def _load_list(self, date_filter: str = None):
        if not self.conn:
            return

        car_no = self.car_no

        with self.conn.cursor() as cur:
            if car_no == "none":
                sql = f"""
                    SELECT id, ts, car_no,
                           ws1_db, ds1_db, ws2_db, ds2_db,
                           img_car_path, img_ws1_path, img_ds1_path, img_ws2_path, img_ds2_path,
                           ws_wheel1_status, ws_wheel2_status,
                           ds_wheel1_status, ds_wheel2_status,
                           img_ws_wheel_path, img_ds_wheel_path
                    FROM `{TABLE_NAME}`
                    WHERE car_no = %s
                    ORDER BY id DESC
                """
                cur.execute(sql, (car_no,))
            else:
                y, m, d = date_filter[0:4], date_filter[4:6], date_filter[6:8]
                date_sql = f"{y}-{m}-{d}"
                sql = f"""
                    SELECT id, ts, car_no,
                           ws1_db, ds1_db, ws2_db, ds2_db,
                           img_car_path, img_ws1_path, img_ds1_path, img_ws2_path, img_ds2_path,
                           ws_wheel1_status, ws_wheel2_status,
                           ds_wheel1_status, ds_wheel2_status,
                           img_ws_wheel_path, img_ds_wheel_path
                    FROM `{TABLE_NAME}`
                    WHERE car_no = %s
                      AND DATE(ts) = %s
                    ORDER BY id DESC
                """
                cur.execute(sql, (car_no, date_sql))

            rows = cur.fetchall()

        self._rows_cache = rows or []

        if hasattr(self, "listWidget"):
            self.listWidget.clear()

        if not self._rows_cache:
            if car_no == "none":
                QMessageBox.information(self, "안내", "car_no='none' 데이터가 없습니다.")
            else:
                QMessageBox.information(self, "안내", f"{date_filter} / {car_no} 데이터가 없습니다.")
            return

        # ✅ 리스트를 "id 기반"으로 만든다 (경로 중복/빈값이어도 안전)
        for r in self._rows_cache:
            _id = r[0]
            ts_val = r[1]
            cno = str(r[2] or "")

            ws1_db = float(r[3] or 0.0)
            ds1_db = float(r[4] or 0.0)
            ws2_db = float(r[5] or 0.0)
            ds2_db = float(r[6] or 0.0)

            try:
                ts_str = ts_val.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts_val, "strftime") else str(ts_val)
            except Exception:
                ts_str = str(ts_val)

            text = f"[{_id}] {ts_str}  car:{cno}  ws1:{ws1_db:.2f} ds1:{ds1_db:.2f} ws2:{ws2_db:.2f} ds2:{ds2_db:.2f}"
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, _id)   # ✅ 클릭 시 이 id로 row 찾음

            if hasattr(self, "listWidget"):
                self.listWidget.addItem(it)

        # 첫 항목 자동 선택
        if hasattr(self, "listWidget") and self.listWidget.count() > 0:
            self.listWidget.setCurrentRow(0)
            self._on_item_clicked(self.listWidget.item(0))

    # ─────────────────────────────────────
    # 색상 / 이미지 표시 유틸
    # ─────────────────────────────────────
    def _color_for_db(self, dbv: float):
        try:
            v = float(dbv)
        except Exception:
            v = 0.0

        if v >= self.v_strong:
            return QColor(255, 30, 0)   # 빨강
        elif v >= self.v_mid:
            return QColor(255, 255, 0)  # 노랑
        elif v >= self.v_weak:
            return QColor(0, 170, 255)  # 파랑
        else:
            return QColor(30, 255, 30)  # 초록

    def _set_db_label(self, label_name: str, value: float):
        if not hasattr(self, label_name):
            return
        w = getattr(self, label_name)

        try:
            v = float(value)
        except Exception:
            v = 0.0

        w.setText(f"{v:.1f}")

        c = self._color_for_db(v)
        font_color = "white" if c == QColor(255, 30, 0) else "black"
        w.setStyleSheet(f"background-color: {c.name()}; color: {font_color};")

    def _show_image_to_label(self, label_name, img_path):
        if not hasattr(self, label_name):
            return
        wgt = getattr(self, label_name)

        if img_path and os.path.exists(img_path):
            pix = QPixmap(img_path)
            scaled = pix.scaled(wgt.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            wgt.setPixmap(scaled)
        else:
            wgt.clear()

    # ─────────────────────────────────────
    # 리스트 클릭 처리
    # ─────────────────────────────────────
    def _on_item_clicked(self, item: QListWidgetItem):
        if not self._rows_cache:
            return

        target_id = item.data(Qt.UserRole)
        row = None
        for r in self._rows_cache:
            if r[0] == target_id:
                row = r
                break
        if row is None:
            row = self._rows_cache[0]

        ts_val = row[1]
        car_no = str(row[2] or "")

        try:
            if hasattr(ts_val, "strftime"):
                date_str = ts_val.strftime("%Y%m%d")
            else:
                s = str(ts_val)
                date_str = s[:10].replace("-", "")
        except Exception:
            date_str = ""

        ws1_db = float(row[3] or 0.0)
        ds1_db = float(row[4] or 0.0)
        ws2_db = float(row[5] or 0.0)
        ds2_db = float(row[6] or 0.0)

        img_car = row[7] or ""
        img_ws1 = row[8] or ""
        img_ds1 = row[9] or ""
        img_ws2 = row[10] or ""
        img_ds2 = row[11] or ""

        ws_wheel1_status = row[12] or ""
        ws_wheel2_status = row[13] or ""
        ds_wheel1_status = row[14] or ""
        ds_wheel2_status = row[15] or ""
        img_ws_wheel = row[16] or ""
        img_ds_wheel = row[17] or ""

        if hasattr(self, "time_label"):
            self.time_label.setText(date_str)
        if hasattr(self, "num_label"):
            self.num_label.setText(car_no)

        self._set_db_label("dB_label1", ws1_db)
        self._set_db_label("dB_label2", ds1_db)
        self._set_db_label("dB_label3", ws2_db)
        self._set_db_label("dB_label4", ds2_db)

        self._show_image_to_label("image_1", img_car)
        self._show_image_to_label("image_2", img_ws1)
        self._show_image_to_label("image_3", img_ds1)
        self._show_image_to_label("image_4", img_ws2)
        self._show_image_to_label("image_5", img_ds2)

        self._show_image_to_label("image_6", img_ws_wheel)
        self._show_image_to_label("image_7", img_ds_wheel)

        if hasattr(self, "wheel_label1"):
            self.wheel_label1.setText(str(ws_wheel1_status))
        if hasattr(self, "wheel_label4"):
            self.wheel_label4.setText(str(ws_wheel2_status))
        if hasattr(self, "wheel_label2"):
            self.wheel_label2.setText(str(ds_wheel1_status))
        if hasattr(self, "wheel_label3"):
            self.wheel_label3.setText(str(ds_wheel2_status))

    # ─────────────────────────────────────
    # 임계값 저장
    # ─────────────────────────────────────
    def _on_threshold_save_clicked(self):
        def _safe_float(le_name, default):
            if not hasattr(self, le_name):
                return default
            le = getattr(self, le_name)
            try:
                return float(le.text())
            except Exception:
                return default

        strong = _safe_float("lineEdit_2", self.v_strong)
        mid = _safe_float("lineEdit_3", self.v_mid)
        weak = _safe_float("lineEdit_4", self.v_weak)
        vmin = _safe_float("lineEdit_5", self.v_min) if hasattr(self, "lineEdit_5") else self.v_min

        w, m, s = sorted([weak, mid, strong])
        self.v_weak, self.v_mid, self.v_strong = w, m, s
        self.v_min = vmin

        self.thresholds["weak"] = self.v_weak
        self.thresholds["mid"] = self.v_mid
        self.thresholds["strong"] = self.v_strong
        self.thresholds["min"] = self.v_min

        save_thresholds_to_json(self.thresholds)

        # 현재 선택 항목 다시 적용
        if hasattr(self, "listWidget"):
            it = self.listWidget.currentItem()
            if it is not None:
                self._on_item_clicked(it)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    car_no_arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if not car_no_arg:
        sys.exit(0)

    win = WindowClass(car_no_arg)
    win.show()
    sys.exit(app.exec_())
