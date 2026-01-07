# viewer.py
# -*- coding:utf-8 -*-
import sys
import os
import pymysql
import json
from datetime import datetime
from PyQt5 import uic
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QListWidgetItem, QMessageBox
)
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt

# 1. 작업 디렉토리 고정 (소스코드 위치 기준)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

# ==== DB 접속 정보 ====
DB_HOST = "127.0.0.1"
DB_USER = "root"
DB_PASSWORD = "0000"
DB_NAME = "posco"
TABLE_NAME = "data"

# 설정 파일 및 UI 파일 경로 (메인 HMI와 공유하는 config.json)
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
UI_PATH = os.path.join(BASE_DIR, "window_check.ui")

class WindowClass(QMainWindow):
    def __init__(self, car_no: str = ""):
        super().__init__()
        try:
            uic.loadUi(UI_PATH, self)
        except Exception as e:
            print(f"UI Load Error: {e}")

        # 1. 이미지 라벨 초기화
        self.img_labels = ["image_1", "image_2", "image_3", "image_4", "image_5", "image_6", "image_7"]
        for name in self.img_labels:
            if hasattr(self, name):
                w = getattr(self, name)
                w.setAlignment(Qt.AlignCenter)
                w.setScaledContents(True)

        # 2. Config 로드 (HMI에서 저장한 색상 기준값 읽기)
        self.load_config()

        # 3. 리스트 클릭 이벤트 연결
        if hasattr(self, "listWidget"):
            self.listWidget.itemClicked.connect(self._on_item_clicked)
        
        # 4. DB 연결 및 초기 데이터 로드
        self.conn = None
        self.car_no = (car_no or "").strip()
        self._rows_cache = []

        self._connect_db()

        # 대차번호 인자 확인 및 타이틀 설정
        if self.car_no and self.car_no.lower() != "none":
            self.setWindowTitle(f"Viewer - Car No: {self.car_no}")
            if hasattr(self, "num_label"):
                self.num_label.setText(self.car_no)
        else:
            self.setWindowTitle("Viewer - All History")
        
        # 데이터 리스트 로드
        self._load_list()

    # =========================================================
    #  설정(Config) 읽기 전용 로직
    # =========================================================
    def load_config(self):
        """
        HMI에서 저장한 config.json 파일을 읽어와 색상 임계값만 메모리에 적재합니다.
        UI에 표시하거나 수정하는 로직은 제거했습니다.
        """
        default_config = {"red": 70.0, "yellow": 60.0, "blue": 50.0}
        
        self.config_data = default_config.copy()

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.config_data.update(data) # 읽어온 값 덮어쓰기
            except Exception as e:
                print(f"Config Read Error: {e}")
        
        # 메모리에 기준값 로드 (색상 판단용)
        self.th_red = float(self.config_data.get("red", 70.0))
        self.th_yel = float(self.config_data.get("yellow", 60.0))
        self.th_blu = float(self.config_data.get("blue", 50.0))
        
        print(f"뷰어 설정 로드 완료: Red={self.th_red}, Yellow={self.th_yel}, Blue={self.th_blu}")

    # =========================================================
    #  DB 및 데이터 표시
    # =========================================================
    def closeEvent(self, e):
        if self.conn: self.conn.close()
        e.accept()

    def _connect_db(self):
        try:
            self.conn = pymysql.connect(
                host=DB_HOST, user=DB_USER, password=DB_PASSWORD,
                database=DB_NAME, charset="utf8", autocommit=True
            )
        except Exception as e:
            QMessageBox.critical(self, "DB 연결 실패", f"{e}")

    def _load_list(self):
        """DB 조회 및 리스트 표시"""
        if not self.conn: return
        
        base_sql = f"""
            SELECT 
                id, created_at, car_no,
                waek_ws1, waek_ds1, waek_ws2, waek_ds2,
                ws_1st_r, ws_1st_p, ws_2nd_r, ws_2nd_p,
                ds_1st_r, ds_1st_p, ds_2nd_r, ds_2nd_p,
                img_car, img_wheel_ws, img_wheel_ds,
                img_waek_ws1, img_waek_ds1, img_waek_ws2, img_waek_ds2
            FROM {TABLE_NAME}
        """
        
        conditions = []
        params = []

        if self.car_no and self.car_no.lower() != "none":
            conditions.append("car_no = %s")
            params.append(self.car_no)
        
        if conditions:
            base_sql += " WHERE " + " AND ".join(conditions)
        
        base_sql += " ORDER BY id DESC"

        try:
            with self.conn.cursor() as cur:
                cur.execute(base_sql, tuple(params))
                self._rows_cache = cur.fetchall()
        except Exception as e:
            print(f"SQL Error: {e}")
            self._rows_cache = []

        if hasattr(self, "listWidget"):
            self.listWidget.clear()
        
        if not self._rows_cache:
            if hasattr(self, "listWidget"):
                self.listWidget.addItem("데이터가 없습니다.")
            return

        for r in self._rows_cache:
            _id = r[0]
            ts = r[1]
            cno = r[2]
            
            date_str = ts.strftime("%Y-%m-%d %H:%M:%S") if isinstance(ts, datetime) else str(ts)
            item_text = f"No: {cno}  |  Date: {date_str}"
            
            it = QListWidgetItem(item_text)
            it.setData(Qt.UserRole, _id)
            self.listWidget.addItem(it)

        # 첫 번째 항목 자동 선택
        if self.listWidget.count() > 0:
            self.listWidget.setCurrentRow(0)
            self._on_item_clicked(self.listWidget.item(0))

    def _on_item_clicked(self, item):
        target_id = item.data(Qt.UserRole)
        if not target_id: return

        row = next((r for r in self._rows_cache if r[0] == target_id), None)
        if not row: return
        
        ts_val = row[1]
        car_no = row[2]
        
        vals = {
            "ws1": float(row[3] or 0), "ds1": float(row[4] or 0),
            "ws2": float(row[5] or 0), "ds2": float(row[6] or 0)
        }
        
        def fmt_s(r, p):
             return f"{r} | {p}" if r and p else "-"

        ws1_st = fmt_s(row[7], row[8])
        ws2_st = fmt_s(row[9], row[10])
        ds1_st = fmt_s(row[11], row[12])
        ds2_st = fmt_s(row[13], row[14])
        
        imgs = {
            "image_1": row[15], "image_6": row[16], "image_7": row[17], 
            "image_2": row[18], "image_3": row[19], "image_4": row[20], "image_5": row[21], 
        }

        # 날짜 표시
        if hasattr(self, "time_label"):
            date_only = ts_val.strftime("%Y-%m-%d") if isinstance(ts_val, datetime) else str(ts_val)[:10]
            self.time_label.setText(date_only)

        # 대차번호 표시
        if hasattr(self, "num_label"): 
            self.num_label.setText(str(car_no))

        # 소음 값 및 배경색 표시 (여기가 중요: 로드한 config 적용)
        self._set_db_label("dB_label1", vals["ws1"])
        self._set_db_label("dB_label2", vals["ds1"])
        self._set_db_label("dB_label3", vals["ws2"])
        self._set_db_label("dB_label4", vals["ds2"])

        # 휠 상태 텍스트
        if hasattr(self, "wheel_label1"): self.wheel_label1.setText(ws1_st) 
        if hasattr(self, "wheel_label4"): self.wheel_label4.setText(ws2_st) 
        if hasattr(self, "wheel_label2"): self.wheel_label2.setText(ds1_st) 
        if hasattr(self, "wheel_label3"): self.wheel_label3.setText(ds2_st) 

        # 이미지 표시
        for lname, path in imgs.items():
            self._show_image_to_label(lname, path)

    def _set_db_label(self, label_name, val):
        """값에 따라 라벨 배경색 변경 (로드된 Config 기준 사용)"""
        if not hasattr(self, label_name): return
        w = getattr(self, label_name)
        w.setText(f"{val:.1f}")
        
        # Config 기준값 비교 (load_config에서 읽어온 값)
        if val > self.th_red: 
            color = "red"
            font_c = "white"
        elif val > self.th_yel: 
            color = "yellow"
            font_c = "black"
        elif val > self.th_blu: 
            color = "#00BFFF" # Deep Sky Blue
            font_c = "black"
        else:
            color = "white"
            font_c = "black"
        
        w.setStyleSheet(f"background-color: {color}; color: {font_c}; border: 1px solid gray;")

    def _show_image_to_label(self, label_name, path):
        if not hasattr(self, label_name): return
        label = getattr(self, label_name)
        
        if path and os.path.exists(path):
            pix = QPixmap(path)
            label.setPixmap(pix.scaled(label.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        else:
            label.setText("No Image")
            label.setStyleSheet("background-color: lightgray; border: 1px solid gray;")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    car_no_arg = sys.argv[1] if len(sys.argv) > 1 else "none"
    win = WindowClass(car_no_arg)
    win.show()
    sys.exit(app.exec_())