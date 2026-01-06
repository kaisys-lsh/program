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

# 작업 디렉토리 고정
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ==== DB 접속 정보 ====
DB_HOST = "127.0.0.1"
DB_USER = "root"
DB_PASSWORD = "0000"
DB_NAME = "posco"
TABLE_NAME = "data"

# 설정 파일 경로 (main.py와 동일한 위치의 파일 사용)
CONFIG_FILE = "config.json"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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

        # 2. [수정] 설정(Config) 불러오기 
        # Main에서 생성한 config.json을 읽어서 기준값으로 사용합니다.
        self.load_config()

        # 3. 이벤트 연결
        if hasattr(self, "listWidget"):
            self.listWidget.itemClicked.connect(self._on_item_clicked)
        
        # 설정 저장 버튼 (필요시 뷰어에서도 수정 후 저장하여 Main에 반영)
        if hasattr(self, "pushButton_2"):
            self.pushButton_2.clicked.connect(self.save_config)

        # 4. DB 연결 및 데이터 로드
        self.conn = None
        self.car_no = (car_no or "").strip()
        self._rows_cache = []

        self._connect_db()

        # 대차번호에 따라 타이틀 설정 및 조회
        if self.car_no:
            if self.car_no != "none":
                self.setWindowTitle(f"Viewer - Car No: {self.car_no}")
            else:
                self.setWindowTitle("Viewer - All History")
            
            self._load_list()

    # =========================================================
    #  설정(Config) 관리 로직
    # =========================================================
    def load_config(self):
        """config.json 파일을 읽어와 임계값을 설정합니다."""
        # 기본값 설정 (파일이 없을 경우 대비)
        default_config = {"red": 70.0, "yellow": 60.0, "blue": 50.0}
        
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    self.config_data = json.load(f)
            except Exception as e:
                print(f"Config Load Error: {e}")
                self.config_data = default_config
        else:
            self.config_data = default_config

        # JSON 파일의 값으로 변수 설정
        self.th_red = float(self.config_data.get("red", 70.0))
        self.th_yel = float(self.config_data.get("yellow", 60.0))
        self.th_blu = float(self.config_data.get("blue", 50.0))

        # UI에 현재 기준값 표시 (사용자 확인용)
        if hasattr(self, "lineEdit_2"): self.lineEdit_2.setText(str(self.th_red))
        if hasattr(self, "lineEdit_3"): self.lineEdit_3.setText(str(self.th_yel))
        if hasattr(self, "lineEdit_4"): self.lineEdit_4.setText(str(self.th_blu))

    def save_config(self):
        """뷰어에서 값을 수정하고 저장하면 config.json을 갱신합니다."""
        try:
            new_red = float(self.lineEdit_2.text())
            new_yel = float(self.lineEdit_3.text())
            new_blu = float(self.lineEdit_4.text())

            self.config_data["red"] = new_red
            self.config_data["yellow"] = new_yel
            self.config_data["blue"] = new_blu

            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=4)

            # 내부 변수 즉시 갱신
            self.th_red = new_red
            self.th_yel = new_yel
            self.th_blu = new_blu

            QMessageBox.information(self, "저장 완료", "설정값이 저장되었습니다.")
            
            # 현재 화면 갱신을 위해 리스트 재클릭 처리
            if hasattr(self, "listWidget"):
                item = self.listWidget.currentItem()
                if item: self._on_item_clicked(item)

        except ValueError:
            QMessageBox.warning(self, "오류", "숫자만 입력해주세요.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"저장 실패: {e}")

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
                rows = cur.fetchall()
                self._rows_cache = rows
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
            w1 = r[3] if r[3] else 0
            d1 = r[4] if r[4] else 0
            
            ts_str = str(ts)
            item_text = f"[{_id}] {ts_str} | Car: {cno} | W1:{w1:.1f} / D1:{d1:.1f}"
            
            it = QListWidgetItem(item_text)
            it.setData(Qt.UserRole, _id)
            self.listWidget.addItem(it)

        if self.listWidget.count() > 0:
            self.listWidget.setCurrentRow(0)
            self._on_item_clicked(self.listWidget.item(0))

    def _on_item_clicked(self, item):
        target_id = item.data(Qt.UserRole)
        if not target_id: return

        row = next((r for r in self._rows_cache if r[0] == target_id), None)
        if not row: return
        
        # 0:id, 1:ts, 2:car_no, ...
        car_no = row[2]
        ts_val = row[1]
        
        vals = {
            "ws1": float(row[3] or 0), "ds1": float(row[4] or 0),
            "ws2": float(row[5] or 0), "ds2": float(row[6] or 0)
        }
        
        # 휠 상태 텍스트
        def fmt_rot(val): return str(val) if val else "-" 
        def fmt_pos(val): return str(val) if val else "-"
        
        ws1_st = f"{fmt_rot(row[7])}/{fmt_pos(row[8])}"
        ws2_st = f"{fmt_rot(row[9])}/{fmt_pos(row[10])}"
        ds1_st = f"{fmt_rot(row[11])}/{fmt_pos(row[12])}"
        ds2_st = f"{fmt_rot(row[13])}/{fmt_pos(row[14])}"
        
        imgs = {
            "image_1": row[15], "image_6": row[16], "image_7": row[17], 
            "image_2": row[18], "image_3": row[19], "image_4": row[20], "image_5": row[21], 
        }

        # [수정] 날짜 표시 (YYYY-MM-DD 형식만 표시)
        if hasattr(self, "time_label"):
            date_str = ""
            if isinstance(ts_val, datetime):
                date_str = ts_val.strftime("%Y-%m-%d")
            else:
                # datetime 객체가 아니고 문자열일 경우 앞 10자리만 자름
                date_str = str(ts_val)[:10]
            self.time_label.setText(date_str)

        if hasattr(self, "num_label"): 
            self.num_label.setText(str(car_no))

        # 소음 센서 값 및 색상 표시
        self._set_db_label("dB_label1", vals["ws1"])
        self._set_db_label("dB_label2", vals["ds1"])
        self._set_db_label("dB_label3", vals["ws2"])
        self._set_db_label("dB_label4", vals["ds2"])

        if hasattr(self, "wheel_label1"): self.wheel_label1.setText(ws1_st) 
        if hasattr(self, "wheel_label4"): self.wheel_label4.setText(ws2_st) 
        if hasattr(self, "wheel_label2"): self.wheel_label2.setText(ds1_st) 
        if hasattr(self, "wheel_label3"): self.wheel_label3.setText(ds2_st) 

        for lname, path in imgs.items():
            self._show_image_to_label(lname, path)

    def _set_db_label(self, label_name, val):
        if not hasattr(self, label_name): return
        w = getattr(self, label_name)
        w.setText(f"{val:.1f}")
        
        # [수정] 색상 결정 로직 (기준값: Config 사용)
        # Red > Yellow > Blue > (Else: White)
        
        color = "white"  # [수정] 기본 배경색 흰색
        font_c = "black" # [수정] 기본 폰트 검정
        
        if val > self.th_red: 
            color = "red"
            font_c = "white"
        elif val > self.th_yel: 
            color = "yellow"
        elif val > self.th_blu: 
            color = "#00BFFF" # Deep Sky Blue
        
        # 나머지는 초기값인 white/black 유지
        
        w.setStyleSheet(f"background-color: {color}; color: {font_c}; border: 1px solid gray;")

    def _show_image_to_label(self, label_name, path):
        if not hasattr(self, label_name): return
        label = getattr(self, label_name)
        if path and os.path.exists(path):
            pix = QPixmap(path)
            label.setPixmap(pix.scaled(label.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        else:
            label.setText("No Image")
            label.setStyleSheet("background-color: lightgray;")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    car_no_arg = sys.argv[1] if len(sys.argv) > 1 else "none"
    win = WindowClass(car_no_arg)
    win.show()
    sys.exit(app.exec_())