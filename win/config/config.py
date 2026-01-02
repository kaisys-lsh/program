# config/config.py
# ==================================================
# 통합 설정
# - 경로 / 네트워크(ZMQ)
# - 카메라/CRY 장비
# - DB / 저장 경로
# - 앱 정책 (기존 app_config 통합)
# ==================================================

import os
import struct

# ==================================================
# [1] 프로젝트 경로
# ==================================================
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CONFIG_DIR)

UI_PATH = os.path.join(PROJECT_DIR, "ui", "window_hmi.ui")

# ⚠️ 주의:
# 다른 모듈이 상대경로에 의존한다면 유지
# 아니라면 삭제 권장
os.chdir(CONFIG_DIR)

# ==================================================
# [2] ZMQ 통신
# ==================================================
# Linux 서버(PUSH) → Windows HMI(PULL)
ZMQ_PULL_ADDR = "tcp://192.168.0.103:5577"

# (구형 호환) struct 기반 통신용
STRUCT_FORMAT = "<ifii"
STRUCT_SIZE = struct.calcsize(STRUCT_FORMAT)

# ZMQ 시작 시 과거 메시지 쏟아짐 방지
ZMQ_DROP_OLD_MESSAGES_ON_START = True
ZMQ_START_GRACE_MS = 500

# ==================================================
# [3] CRY API 계정
# ==================================================
CRY_USER = "admin"
CRY_PW = "crysound"

# ==================================================
# [4] 카메라 / RTSP / CRY 장비
# ==================================================

# --- 대차 카메라 ---
CRY_CAM_IP = "192.168.11.88"
CRY_CAM_PORT = 90
CRY_CAM_USE_HTTPS = False
RTSP_CAM = "rtsp://192.168.11.88:8554/live/test"

# --- Zone1 (WS1 / DS1) ---
CRY_A1_IP = "192.168.11.88"
CRY_A1_PORT = 90
CRY_A1_USE_HTTPS = False
RTSP_A1 = "rtsp://192.168.11.88:8554/live/test"

CRY_B1_IP = "192.168.11.88"
CRY_B1_PORT = 90
CRY_B1_USE_HTTPS = False
RTSP_B1 = "rtsp://192.168.11.88:8554/live/test"

# --- Zone2 (WS2 / DS2) ---
CRY_A2_IP = "192.168.11.88"
CRY_A2_PORT = 90
CRY_A2_USE_HTTPS = False
RTSP_A2 = "rtsp://192.168.11.88:8554/live/test"

CRY_B2_IP = "192.168.11.88"
CRY_B2_PORT = 90
CRY_B2_USE_HTTPS = False
RTSP_B2 = "rtsp://192.168.11.88:8554/live/test"

# --- Wheel 전용 ---
RTSP_WHEEL_WS = "rtsp://192.168.11.88:8554/live/test"
RTSP_WHEEL_DS = "rtsp://192.168.11.88:8554/live/test"

# CRY 상태 폴링
CRY_INTERVAL_SEC = 1
CRY_TIMEOUT_SEC = 5

# ==================================================
# [5] MariaDB
# ==================================================
DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_USER = "root"
DB_PW = "0000"

DB_NAME = "posco"
TABLE_NAME = "data"

# ==================================================
# [6] 데이터 저장
# ==================================================
DATA_ROOT = r"D:\DATA"

# ==================================================
# [7] 임계값 (UI 색칠용)
# ==================================================
THRESHOLDS_JSON = os.path.join(CONFIG_DIR, "thresholds.json")
DEFAULT_THRESHOLDS = {
    "weak": 3.0,
    "mid": 4.0,
    "strong": 5.0,
    "min": 0.0,
}

# ==================================================
# [8] 앱 동작 정책 (구 app_config)
# ==================================================

# --- 개발/테스트 ---
USE_DUMMY_CRY = True
USE_DUMMY_CAMERA = True

# --- Zone2 매칭 보정 ---
DELAY_COUNT = 7

# --- UI 표시 ---
SHOW_ONLY_DB_COMPLETE = True
MAX_TABLE_ROWS = 172

# --- DB Polling ---
DB_POLL_INTERVAL_SEC = 0.2

# --- 스냅샷 ---
SNAPSHOT_SEC = 1.0

# --- 라이브 영상 ---
SHOW_LIVE_VIDEO = False  # CPU 절약용

# ==================================================
# [9] ✅ 구버전 호환 alias (기존 코드 안 깨지게)
# ==================================================

# ZMQ
PULL_CONNECT1 = ZMQ_PULL_ADDR  # main_run.py 등 기존 코드 호환

# RTSP (기존 이름 유지)
RTSP_CAM_IP = RTSP_CAM

RTSP_A1_IP = RTSP_A1
RTSP_B1_IP = RTSP_B1
RTSP_A2_IP = RTSP_A2
RTSP_B2_IP = RTSP_B2

RTSP_C1_IP = RTSP_WHEEL_WS
RTSP_C2_IP = RTSP_WHEEL_DS
