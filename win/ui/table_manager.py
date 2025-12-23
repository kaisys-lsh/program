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
        self.max_rows = max_rows

        self._init_table()

    def _init_table(self):
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(["대차", "WS1", "DS1", "WS2", "DS2", "WS휠1", "WS휠2", "DS휠1", "DS휠2"])
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

    def insert_record(self, rec):
        row = 0
        self.table.insertRow(row)

        def setcol(c, text, dbv=None):
            it = QTableWidgetItem(text)
            self.table.setItem(row, c, it)
            if dbv is not None:
                it.setBackground(QColor(color_for_db(self.thresholds, dbv)))
            it.setForeground(QColor("black"))

        car_no = rec.get("car_no", "")
        setcol(0, str(car_no))
        setcol(1, "{0:.2f}".format(float(rec.get("ws1_db", 0.0))), rec.get("ws1_db", 0.0))
        setcol(2, "{0:.2f}".format(float(rec.get("ds1_db", 0.0))), rec.get("ds1_db", 0.0))
        setcol(3, "{0:.2f}".format(float(rec.get("ws2_db", 0.0))), rec.get("ws2_db", 0.0))
        setcol(4, "{0:.2f}".format(float(rec.get("ds2_db", 0.0))), rec.get("ds2_db", 0.0))
        setcol(5, "")
        setcol(6, "")
        setcol(7, "")
        setcol(8, "")

        if self.table.rowCount() > self.max_rows:
            self.table.removeRow(self.table.rowCount() - 1)

    def find_row(self, car_no_str):
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

        item.setText(status_text)
        item.setBackground(QColor(wheel_color_for_status(status_text)))
        item.setForeground(QColor("black"))

    def update_wheel_status(self, car_no_str, pos, status_1st, status_2nd):
        row = self.find_row(car_no_str)
        if row is None:
            return False

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
