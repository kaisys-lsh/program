# config/config.py
# --------------------------------------------------
# 공통 설정
# - 네트워크(ZMQ)
# - CRY / RTSP 장비 주소
# - DB 접속
# - 데이터 저장 경로
# --------------------------------------------------

import os
import struct

# --------------------------------------------------
# 경로
# --------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# (기존 코드 호환) 실행 위치 고정이 필요하면 유지
# 단, 다른 모듈에서 상대경로를 많이 쓰면 도움이 됨
os.chdir(BASE_DIR)

# --------------------------------------------------
# ZMQ
# --------------------------------------------------
# Linux 서버(PUSH) -> Windows(HMI PULL)
PULL_CONNECT1 = "tcp://192.168.0.103:5577"

# (구형/호환) 구조체를 쓰는 경우가 있으면 유지
STRUCT_FORMAT = "<ifii"
STRUCT_SIZE = struct.calcsize(STRUCT_FORMAT)

# --------------------------------------------------
# CRY API 계정
# --------------------------------------------------
CRY_USER = "admin"
CRY_PW = "crysound"

# --------------------------------------------------
# 장비 IP/PORT/RTSP
# --------------------------------------------------
# CAM (대차영상)
CRY_CAM_IP = "192.168.11.88"
CRY_CAM_PORT = 90
CRY_CAM_USE_HTTPS = False
RTSP_CAM_IP = "rtsp://192.168.11.88:8554/live/test"

# Zone1 (WS1/DS1)
CRY_A1_IP = "192.168.11.88"
CRY_A1_PORT = 90
CRY_A1_USE_HTTPS = False
RTSP_A1_IP = "rtsp://192.168.11.88:8554/live/test"

CRY_B1_IP = "192.168.11.88"
CRY_B1_PORT = 90
CRY_B1_USE_HTTPS = False
RTSP_B1_IP = "rtsp://192.168.11.88:8554/live/test"

# Zone2 (WS2/DS2)
CRY_A2_IP = "192.168.11.88"
CRY_A2_PORT = 90
CRY_A2_USE_HTTPS = False
RTSP_A2_IP = "rtsp://192.168.11.88:8554/live/test"

CRY_B2_IP = "192.168.11.88"
CRY_B2_PORT = 90
CRY_B2_USE_HTTPS = False
RTSP_B2_IP = "rtsp://192.168.11.88:8554/live/test"

# Wheel (WS/DS 카메라)
RTSP_C1_IP = "rtsp://192.168.11.88:8554/live/test"  # wheel_ws
RTSP_C2_IP = "rtsp://192.168.11.88:8554/live/test"  # wheel_ds

# CRY 폴링 주기
CRY_INTERVAL_SEC = 1
CRY_TIMEOUT_SEC = 5

# --------------------------------------------------
# MariaDB
# --------------------------------------------------
DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_USER = "root"
DB_PW = "0000"

DB_NAME = "posco"
TABLE_NAME = "data"

# --------------------------------------------------
# 이미지 저장 루트
# --------------------------------------------------
DATA_ROOT = r"D:\DATA"

# --------------------------------------------------
# 임계값 JSON (색칠용) - 유지할 경우
# --------------------------------------------------
THRESHOLDS_JSON = os.path.join(BASE_DIR, "thresholds.json")
DEFAULT_THRESHOLDS = {"weak": 3.0, "mid": 4.0, "strong": 5.0, "min": 0.0}
