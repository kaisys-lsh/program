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

        # ✅ 버튼에 "090\n정상" 이런 식으로 들어오므로 첫 줄만 사용
        first_line = raw.splitlines()[0].strip()

        # ✅ N / none 처리 (N\n정상도 여기서 OK)
        if first_line.upper() == "N":
            car_no = "none"
        else:
            # ✅ 3자리 번호만 뽑기 (예: "090", "090 비정상" 등 방어)
            m = re.search(r"\b(\d{3})\b", first_line)
            car_no = m.group(1) if m else first_line.strip()

        # ✅ 유효성 체크
        if (not car_no) or (car_no != "none" and (not car_no.isdigit() or len(car_no) != 3)):
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
