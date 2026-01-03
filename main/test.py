# hmi_run.py
import sys
import os
from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.uic import loadUi


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        ui_path = os.path.join(os.path.dirname(__file__), "window_hmi.ui")
        loadUi(ui_path, self)


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
