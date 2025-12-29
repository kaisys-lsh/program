# ui/table_manager.py
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QTableWidgetItem

from utils.color_utils import color_for_db, wheel_color_for_status


class TableManager:
    def __init__(self, table_widget, thresholds, max_rows):
        self.table = table_widget
        self.thresholds = thresholds
        self.max_rows = int(max_rows) if max_rows else 100

        # ✅ event_id -> row index (가장 안전)
        self._row_by_event = {}

        self._init_table()

    def _init_table(self):
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(
            ["대차", "WS1", "DS1", "WS2", "DS2", "WS휠1", "WS휠2", "DS휠1", "DS휠2"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(self.table.NoEditTriggers)
        self.table.setSelectionBehavior(self.table.SelectRows)
        self.table.setSelectionMode(self.table.SingleSelection)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        font = self.table.font()
        font.setPointSize(8)
        self.table.setFont(font)

    def set_thresholds(self, thresholds):
        self.thresholds = thresholds

    def _display_car_no(self, car_no_raw: str):
        s = (car_no_raw or "").strip()
        if not s or s.lower() == "none" or s.upper() == "FFF":
            return "N"
        return s

    def insert_record(self, rec):
        """
        ✅ rec에 event_id가 있으면 그걸로 row를 추적해둔다.
        """
        row = 0
        self.table.insertRow(row)

        event_id = str(rec.get("event_id", "") or "").strip()

        def setcol(c, text, dbv=None):
            it = QTableWidgetItem(text)
            self.table.setItem(row, c, it)
            if dbv is not None:
                it.setBackground(QColor(color_for_db(self.thresholds, dbv)))
            it.setForeground(QColor("black"))
            return it

        car_no = self._display_car_no(rec.get("car_no", ""))
        it0 = setcol(0, str(car_no))

        # ✅ 0번 컬럼 item에 event_id를 심어둠(디버깅/백업용)
        if event_id:
            it0.setData(Qt.UserRole, event_id)

        setcol(1, "{0:.2f}".format(float(rec.get("ws1_db", 0.0))), rec.get("ws1_db", 0.0))
        setcol(2, "{0:.2f}".format(float(rec.get("ds1_db", 0.0))), rec.get("ds1_db", 0.0))
        setcol(3, "{0:.2f}".format(float(rec.get("ws2_db", 0.0))), rec.get("ws2_db", 0.0))
        setcol(4, "{0:.2f}".format(float(rec.get("ds2_db", 0.0))), rec.get("ds2_db", 0.0))
        setcol(5, "")
        setcol(6, "")
        setcol(7, "")
        setcol(8, "")

        # ✅ 기존 row index들이 1칸씩 내려감 → 매핑 갱신
        if self._row_by_event:
            for k in list(self._row_by_event.keys()):
                self._row_by_event[k] = self._row_by_event[k] + 1

        if event_id:
            self._row_by_event[event_id] = row

        # row 제한 초과 시 마지막 row 제거 + 매핑 정리
        if self.table.rowCount() > self.max_rows:
            last = self.table.rowCount() - 1

            # 마지막 row에 심어둔 event_id 제거
            item0 = self.table.item(last, 0)
            if item0 is not None:
                ev = item0.data(Qt.UserRole)
                if ev:
                    ev = str(ev).strip()
                    if ev in self._row_by_event:
                        del self._row_by_event[ev]

            self.table.removeRow(last)

    def find_row_by_event(self, event_id: str):
        if not event_id:
            return None
        event_id = str(event_id).strip()
        return self._row_by_event.get(event_id)

    def find_row_by_car_no(self, car_no_str: str):
        """
        ✅ fallback (event_id가 없을 때만)
        """
        car_no_str = (car_no_str or "").strip()
        if car_no_str.lower() == "none":
            car_no_str = "N"

        rows = self.table.rowCount()
        for r in range(rows):
            item_car = self.table.item(r, 0)
            if item_car is None:
                continue
            if item_car.text().strip() == car_no_str:
                return r
        return None

    def _set_wheel_cell(self, row, col, status_text):
        item = self.table.item(row, col)
        if item is None:
            item = QTableWidgetItem()
            self.table.setItem(row, col, item)

        item.setText(str(status_text))
        item.setBackground(QColor(wheel_color_for_status(status_text)))
        item.setForeground(QColor("black"))

    def update_wheel_status(self, event_id, car_no_str, pos, status_1st, status_2nd):
        """
        ✅ 1순위: event_id로 row 찾기
        ✅ 2순위: car_no로 fallback
        """
        row = self.find_row_by_event(event_id)
        if row is None:
            row = self.find_row_by_car_no(car_no_str)
        if row is None:
            return False

        pos = str(pos or "").strip().upper()
        if pos == "WS":
            col1, col2 = 5, 6
        else:
            col1, col2 = 7, 8

        self._set_wheel_cell(row, col1, status_1st)
        self._set_wheel_cell(row, col2, status_2nd)
        return True

    def repaint_db_cells(self):
        rows = self.table.rowCount()
        for r in range(rows):
            for c in range(1, 5):
                item = self.table.item(r, c)
                if item is None:
                    continue
                text = item.text().strip()
                if not text:
                    continue
                try:
                    v = float(text)
                except Exception:
                    continue
                item.setBackground(QColor(color_for_db(self.thresholds, v)))
                item.setForeground(QColor("black"))
