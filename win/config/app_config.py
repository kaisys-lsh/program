# config/app_config.py
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_PATH = os.path.join(BASE_DIR, "ui", "window_hmi.ui")

# 개발/테스트 옵션
USE_DUMMY_CRY = True
USE_DUMMY_CAMERA = True

# 큐 지연 매칭 (2번구간 붙이는 딜레이)
DELAY_COUNT = 2

# 테이블 최대 행
MAX_TABLE_ROWS = 172

SNAPSHOT_SEC = 1

SHOW_LIVE_VIDEO = False