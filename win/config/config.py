# config.py
import os
import struct

# 작업 폴더를 이 파일이 있는 위치로 고정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

# ─────────────────────────────────────────
# ZMQ / 구조체
# ─────────────────────────────────────────
# 리눅스PC 통신
PULL_CONNECT = "tcp://192.168.0.103:5577"   # 송신 IP에 맞게
#PULL_CONNECT = "tcp://172.30.1.56:5577"   # HOME PC 테스트용
STRUCT_FORMAT = "<ifii"
STRUCT_SIZE = struct.calcsize(STRUCT_FORMAT)

# ─────────────────────────────────────────
# CRY API 기본 설정 (장비별 분리)
# ─────────────────────────────────────────
CRY_USER = "admin"
CRY_PW = "crysound"

# W/S 누풍 장비1
CRY_A1_IP = "192.168.11.88"
CRY_A1_PORT = 90
RTSP_A1_IP = "rtsp://192.168.11.88:8554/live/test"
CRY_A1_USE_HTTPS = False

# D/S 누풍 장비1
CRY_B1_IP = "192.168.11.88"
CRY_B1_PORT = 90
RTSP_B1_IP = "rtsp://192.168.11.88:8554/live/test"
CRY_B1_USE_HTTPS = False

# W/S 누풍 장비2
CRY_A2_IP = "192.168.11.88"
CRY_A2_PORT = 90
RTSP_A2_IP = "rtsp://192.168.11.88:8554/live/test"
CRY_A2_USE_HTTPS = False

# D/S 누풍 장비2
CRY_B2_IP = "192.168.11.88"
CRY_B2_PORT = 90
RTSP_B2_IP = "rtsp://192.168.11.88:8554/live/test"
CRY_B2_USE_HTTPS = False

# W/S 휠 상태
CRY_C1_IP = ""
CRY_C1_PORT = 90
RTSP_C1_IP = "rtsp://192.168.11.88:8554/live/test"
CRY_C1_USE_HTTPS = False

# D/S 휠 상태
CRY_C2_IP = ""
CRY_C2_PORT = 90
RTSP_C2_IP = "rtsp://192.168.11.88:8554/live/test"
CRY_C2_USE_HTTPS = False

CRY_INTERVAL_SEC = 1
CRY_TIMEOUT_SEC = 5

# ─────────────────────────────────────────
# MariaDB 접속 설정
# ─────────────────────────────────────────
DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_USER = "root"
DB_PW   = "0000"   # 실제 암호로 교체

# ─────────────────────────────────────────
# 이미지 저장 루트 경로
# ─────────────────────────────────────────
DATA_ROOT = r"D:\DATA"

# ─────────────────────────────────────────
# 임계값 설정 JSON
# ─────────────────────────────────────────
THRESHOLDS_JSON = os.path.join(BASE_DIR, "thresholds.json")

# 기본값 (weak < mid < strong), min은 선택적으로 사용
DEFAULT_THRESHOLDS = {"weak": 3.0, "mid": 4.0, "strong": 5.0, "min": 0.0}
