# ui/viewer_launcher.py
import os
import re
import sys
import subprocess
from PyQt5 import QtWidgets


class ViewerLauncher:
    def __init__(self, base_dir):
        self.base_dir = base_dir

    def open_for_button(self, parent, btn_text):
        raw = (btn_text or "").strip()
        if not raw:
            QtWidgets.QMessageBox.information(parent, "안내", "버튼에 대차번호가 없습니다.")
            return

        if raw == "N":
            car_no = "none"
        else:
            m = re.search(r"\b(\d{3})\b", raw)
            car_no = m.group(1) if m else raw

        if (not car_no) or (car_no != "none" and not car_no.isdigit()):
            QtWidgets.QMessageBox.information(parent, "안내", "버튼에 대차번호가 없습니다.")
            return

        self._launch_viewer_process(parent, car_no)

    def _launch_viewer_process(self, parent, car_no):
        viewer_py = os.path.join(self.base_dir, "viewer.py")
        if not os.path.exists(viewer_py):
            QtWidgets.QMessageBox.critical(parent, "오류", f"viewer.py 파일을 찾을 수 없습니다.\n{viewer_py}")
            return

        try:
            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

            subprocess.Popen([sys.executable, viewer_py, car_no], creationflags=creationflags)
        except Exception as e:
            QtWidgets.QMessageBox.critical(parent, "실행 오류", f"조회 프로그램 실행 실패:\n{e}")
