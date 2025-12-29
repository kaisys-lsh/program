# ui/button_manager.py
from PyQt5.QtWidgets import QPushButton
from utils.color_utils import color_for_db, wheel_color_for_status


class ButtonManager:
    def __init__(self, window, viewer_launcher, thresholds):
        self.window = window
        self.viewer_launcher = viewer_launcher
        self.thresholds = thresholds

        self.paint_buttons = []
        self.button_labels = []
        self.button_db_values = []
        self.button_wheel_status = []

        self._collect_buttons()

    def _collect_buttons(self):
        self.paint_buttons = []
        i = 1
        while True:
            btn = self.window.findChild(QPushButton, "N_{0}".format(i))
            if btn is None:
                break
            self.paint_buttons.append(btn)
            i += 1

        # ✅ 클릭 시 버튼 텍스트에서 "첫 줄"만 따서 넘김
        for btn in self.paint_buttons:
            btn.clicked.connect(lambda _, b=btn: self._open_by_button_text(b))

        n = len(self.paint_buttons)
        self.button_labels = [""] * n
        self.button_db_values = [None] * n
        self.button_wheel_status = [""] * n

    def _open_by_button_text(self, btn):
        try:
            txt = btn.text()
        except Exception:
            txt = ""

        # ✅ "090\n정상" -> "090" (첫 줄만)
        if txt is None:
            txt = ""
        txt = str(txt).strip()
        if "\n" in txt:
            txt = txt.splitlines()[0].strip()

        self.viewer_launcher.open_for_button(self.window, txt)

    def set_thresholds(self, thresholds):
        self.thresholds = thresholds

    def push_front(self, label_text, db_value, wheel_status):
        self.button_labels.insert(0, str(label_text))
        self.button_db_values.insert(0, db_value)
        self.button_wheel_status.insert(0, wheel_status or "")

        n = len(self.paint_buttons)
        self.button_labels = self.button_labels[:n]
        self.button_db_values = self.button_db_values[:n]
        self.button_wheel_status = self.button_wheel_status[:n]

        self.repaint_all()

    def repaint_all(self):
        for i in range(len(self.paint_buttons)):
            btn = self.paint_buttons[i]

            lbl = self.button_labels[i]
            dbv = self.button_db_values[i]
            status = self.button_wheel_status[i]

            top_color = color_for_db(self.thresholds, dbv)
            bottom_color = wheel_color_for_status(status)

            if status:
                text = "{0}\n{1}".format(lbl, status)
            else:
                text = str(lbl)

            btn.setText(text)

            f = btn.font()
            f.setPointSize(7)
            btn.setFont(f)

            btn.setStyleSheet("""
                QPushButton {{
                    color: black;
                    border: 1px solid #222;
                    padding: 0px;
                    font-size: 8pt;
                    background: qlineargradient(
                        x1:0, y1:0, x2:0, y2:1,
                        stop:0.0 {0},
                        stop:0.60 {0},
                        stop:0.60 {1},
                        stop:1.0 {1}
                    );
                }}
            """.format(top_color, bottom_color))
