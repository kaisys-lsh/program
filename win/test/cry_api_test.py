# test/cry_api_test.py
import math
import time
import random
from PyQt5.QtCore import QThread, pyqtSignal


class CryApiThread(QThread):   # 실제 클래스랑 이름만 맞추면 됨
    db_ready = pyqtSignal(float)
    text_ready = pyqtSignal(str)

    _next_id = 0   # 클래스 전체에서 공유하는 카운터

    def __init__(self, *args, interval_sec=1, **kwargs):
        super().__init__()
        self.interval_sec = max(1, int(interval_sec))
        self._running = True

        # --- 여기서 각 인스턴스마다 다른 값 세팅 ---
        self.my_id = CryApiThread._next_id
        CryApiThread._next_id += 1

        # 장비마다 다른 기준 dB / 진폭 / 초기 위상
        random.seed(self.my_id)          # 인스턴스마다 다른 seed
        self.base = 50 + self.my_id * 3  # 50, 53, 56, ...
        self.amp = 5 + random.random()*5 # 5~10 사이
        self.phase = random.random()*6.28  # 0~2π 사이

    def stop(self):
        self._running = False

    def run(self):
        t = self.phase
        self.text_ready.emit(f"[DUMMY {self.my_id}] 카메라 없이 테스트 모드 시작")
        while self._running:
            value = self.base + self.amp * math.sin(t)
            self.db_ready.emit(value)
            self.text_ready.emit(f"[DUMMY {self.my_id}] db={value:.1f}")
            t += 0.3
            for _ in range(self.interval_sec * 10):
                if not self._running:
                    break
                time.sleep(0.1)
