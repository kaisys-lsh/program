# run_both.py
# -*- coding: utf-8 -*-

import os
import sys
import subprocess

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON   = sys.executable  # 지금 env의 파이썬 그대로 사용

def main():
    ws_path = os.path.join(THIS_DIR, "CheckWSWheelStatus.py")
    ds_path = os.path.join(THIS_DIR, "CheckDSWheelStatus.py")

    # WS, DS 두 프로세스 동시에 실행
    p_ws = subprocess.Popen([PYTHON, ws_path])
    p_ds = subprocess.Popen([PYTHON, ds_path])

    # 둘 다 끝날 때까지 대기
    p_ws.wait()
    p_ds.wait()

if __name__ == "__main__":
    main()
