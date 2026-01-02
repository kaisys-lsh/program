# win/managers/ui_manager.py
# -*- coding: utf-8 -*-
import os
from PyQt5 import uic, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import QPushButton, QTableWidgetItem, QDialog

from utils.color_json_utils import color_for_db, wheel_color_for_status
from utils.image_utils import set_label_pixmap_fill

# ==================================================
# 1. 뷰어 런처 (ViewerLauncher 통합)
# ==================================================
class ViewerLauncher:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.viewer_ui_path = os.path.join(base_dir, "ui", "window_check.ui")  # 경로 가정

    def open_for_button(self, parent_window, car_no):
        """버튼 클릭 시 상세 화면(Dialog) 띄우기"""
        # 실제 구현은 win/viewer.py 로직을 참고하여 다이얼로그 띄우는 코드 작성
        # 여기서는 구조만 잡음
        print(f"[UI] 상세 보기 열기: {car_no}")
        # dlg = QDialog(parent_window)
        # uic.loadUi(self.viewer_ui_path, dlg)
        # dlg.exec_()


# ==================================================
# 2. 버튼 매니저 (상단 그라데이션 버튼들)
# ==================================================
class ButtonManager:
    def __init__(self, window, viewer_launcher, thresholds):
        self.window = window
        self.viewer_launcher = viewer_launcher
        self.thresholds = thresholds
        
        self.buttons = []
        self.labels = []
        self.db_values = []
        self.statuses = []
        
        self._init_buttons()

    def _init_buttons(self):
        """UI에서 N_1, N_2... 버튼 찾아 리스트화"""
        i = 1
        while True:
            btn = self.window.findChild(QPushButton, f"N_{i}")
            if btn is None:
                break
            btn.clicked.connect(lambda _, b=btn: self._on_click(b))
            self.buttons.append(btn)
            i += 1
            
        n = len(self.buttons)
        self.labels = [""] * n
        self.db_values = [0.0] * n
        self.statuses = [""] * n

    def _on_click(self, btn):
        txt = btn.text().splitlines()[0] if btn.text() else ""
        self.viewer_launcher.open_for_button(self.window, txt)

    def set_thresholds(self, thresholds):
        self.thresholds = thresholds

    def push_new_data(self, car_no, max_db, overall_status):
        """새 데이터가 오면 큐처럼 밀어넣기"""
        self.labels.insert(0, str(car_no))
        self.db_values.insert(0, float(max_db))
        self.statuses.insert(0, str(overall_status))

        # 리스트 크기 유지
        n = len(self.buttons)
        self.labels = self.labels[:n]
        self.db_values = self.db_values[:n]
        self.statuses = self.statuses[:n]

        self.repaint_all()

    def repaint_all(self):
        for i, btn in enumerate(self.buttons):
            lbl = self.labels[i]
            dbv = self.db_values[i]
            stat = self.statuses[i]

            top_col = color_for_db(self.thresholds, dbv)
            bot_col = wheel_color_for_status(stat)

            text = f"{lbl}\n{stat}" if stat else lbl
            btn.setText(text)
            
            # 스타일시트로 그라데이션 적용
            btn.setStyleSheet(f"""
                QPushButton {{
                    color: black; border: 1px solid #333; font-size: 8pt;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {top_col}, stop:0.6 {top_col},
                        stop:0.6 {bot_col}, stop:1.0 {bot_col});
                }}
            """)


# ==================================================
# 3. 테이블 매니저 (좌측 리스트)
# ==================================================
class TableManager:
    def __init__(self, table_widget, thresholds, max_rows=100):
        self.table = table_widget
        self.thresholds = thresholds
        self.max_rows = max_rows
        self._init_header()

    def _init_header(self):
        cols = ["대차", "WS1", "DS1", "WS2", "DS2", "WS휠1", "WS휠2", "DS휠1", "DS휠2"]
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

    def set_thresholds(self, thresholds):
        self.thresholds = thresholds

    def insert_record(self, rec):
        self.table.insertRow(0)
        
        # 헬퍼 함수: 셀 생성 및 색상 적용
        def make_item(text, db_val=None, is_wheel=False):
            it = QTableWidgetItem(str(text))
            it.setTextAlignment(Qt.AlignCenter)
            if db_val is not None:
                it.setBackground(QColor(color_for_db(self.thresholds, db_val)))
            if is_wheel:
                it.setBackground(QColor(wheel_color_for_status(text)))
            return it

        # 데이터 파싱
        car_no = rec.get("car_no", "N")
        if str(car_no).lower() == "none": car_no = "N"

        self.table.setItem(0, 0, make_item(car_no))
        self.table.setItem(0, 1, make_item(f"{rec.get('ws1_db',0):.2f}", rec.get('ws1_db',0)))
        self.table.setItem(0, 2, make_item(f"{rec.get('ds1_db',0):.2f}", rec.get('ds1_db',0)))
        self.table.setItem(0, 3, make_item(f"{rec.get('ws2_db',0):.2f}", rec.get('ws2_db',0)))
        self.table.setItem(0, 4, make_item(f"{rec.get('ds2_db',0):.2f}", rec.get('ds2_db',0)))
        
        # 휠 상태 (빈칸일 수 있음)
        self.table.setItem(0, 5, make_item(rec.get("ws_wheel1_status", ""), is_wheel=True))
        self.table.setItem(0, 6, make_item(rec.get("ws_wheel2_status", ""), is_wheel=True))
        self.table.setItem(0, 7, make_item(rec.get("ds_wheel1_status", ""), is_wheel=True))
        self.table.setItem(0, 8, make_item(rec.get("ds_wheel2_status", ""), is_wheel=True))

        # Row 제한
        if self.table.rowCount() > self.max_rows:
            self.table.removeRow(self.table.rowCount() - 1)

    def repaint_db_cells(self):
        """임계값 변경 시 DB 컬럼 색상 재계산"""
        for r in range(self.table.rowCount()):
            for c in range(1, 5): # DB 컬럼 인덱스
                item = self.table.item(r, c)
                if item:
                    try:
                        val = float(item.text())
                        item.setBackground(QColor(color_for_db(self.thresholds, val)))
                    except: pass


# ==================================================
# 4. 통합 UI 컨트롤러 (MainRun이 얘랑만 대화함)
# ==================================================
class MainUiController:
    def __init__(self, window, base_dir, thresholds):
        self.window = window
        self.thresholds = thresholds
        
        # 하위 매니저 생성
        self.launcher = ViewerLauncher(base_dir)
        self.btn_mgr = ButtonManager(window, self.launcher, thresholds)
        self.tbl_mgr = TableManager(window.tableWidget, thresholds)

        # 위젯 매핑 (MainRun의 하드코딩 제거 목적)
        # key: cam_id -> value: (ImageWidget, TextWidget)
        self.widget_map = {
            "cam1": (window.image_1, None),
            "ws1":  (window.image_2, window.msg_2),
            "ds1":  (window.image_3, window.msg_3),
            "ws2":  (window.image_4, window.msg_6),
            "ds2":  (window.image_5, window.msg_5),
            "wheel_ws": (window.image_6, None),
            "wheel_ds": (window.image_7, None),
        }

        # 휠 상태 라벨 (WS/DS)
        self.wheel_labels_ws = (window.msg_4, window.msg_8) # 1축, 2축
        self.wheel_labels_ds = (window.msg_7, window.msg_9)

    # --- Live Update Methods ---
    def update_live_image(self, cam_id, qimg):
        """영상 프레임 업데이트"""
        widgets = self.widget_map.get(cam_id)
        if widgets and widgets[0]:
            set_label_pixmap_fill(widgets[0], QPixmap.fromImage(qimg))

    def update_sensor_text(self, cam_id, value):
        """소음 센서 값 업데이트"""
        widgets = self.widget_map.get(cam_id)
        if widgets and widgets[1]:
            widgets[1].setText(f"{value:.2f}")

    def update_wheel_status_label(self, pos, s1, s2):
        """휠 상태 텍스트 (WS/DS) 업데이트"""
        if pos == "WS":
            self.wheel_labels_ws[0].setText(s1)
            self.wheel_labels_ws[1].setText(s2)
        elif pos == "DS":
            self.wheel_labels_ds[0].setText(s1)
            self.wheel_labels_ds[1].setText(s2)

    def clear_wheel_labels(self):
        """새 차 진입 시 휠 라벨 초기화"""
        for lbl in self.wheel_labels_ws + self.wheel_labels_ds:
            lbl.setText("")

    # --- Record Update Methods ---
    def add_db_record(self, rec):
        """DB 폴링 결과 -> 테이블 및 버튼 갱신"""
        # 1. 테이블 추가
        self.tbl_mgr.insert_record(rec)
        
        # 2. 버튼 추가
        car_no = rec.get("car_no", "N")
        if str(car_no).lower() == "none": car_no = "N"
        
        # DB 최대값 추출
        dbs = []
        for k in ["ws1_db", "ds1_db", "ws2_db", "ds2_db"]:
            try: dbs.append(float(rec.get(k, 0)))
            except: dbs.append(0.0)
        
        self.btn_mgr.push_new_data(car_no, max(dbs), rec.get("wheel_overall", ""))

    # --- Threshold Methods ---
    def get_threshold_inputs(self):
        """UI 입력창(LineEdit)에서 값 읽어오기"""
        try:
            return {
                "strong": float(self.window.lineEdit_2.text()),
                "mid":    float(self.window.lineEdit_3.text()),
                "weak":   float(self.window.lineEdit_4.text())
            }
        except:
            return None

    def apply_new_thresholds(self, new_thr):
        """새 임계값 적용 및 리페인트"""
        # 정렬 (안전장치)
        vals = sorted(new_thr.values())
        self.thresholds.update({"weak": vals[0], "mid": vals[1], "strong": vals[2]})
        
        self.btn_mgr.set_thresholds(self.thresholds)
        self.tbl_mgr.set_thresholds(self.thresholds)
        
        self.btn_mgr.repaint_all()
        self.tbl_mgr.repaint_db_cells()
        
        return self.thresholds