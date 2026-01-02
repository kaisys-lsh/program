# config/config.py
# --------------------------------------------------
# 프로젝트 전역 설정 (Configuration)
# --------------------------------------------------
import torch

# ==================================================
# 1. 시스템 기본 설정 (성능 / 디버깅)
# ==================================================
FPS                 = 0.85      # 전체 처리 FPS 목표값
JPEG_QUALITY        = 80        # 전송 이미지 품질 (1~100)
SHOW_DEBUG_WINDOW   = True      # 로컬 디버그 창 표시 여부

# 디버그 그리기 옵션
DRAW_MARK_BOX       = False     # 마크(Mark) 박스 그리기
DRAW_DIGIT_BOX      = True      # 숫자(Digit) 박스 그리기

# 해상도 설정
INFER_MAX_WIDTH     = 960       # 추론 시 이미지 리사이즈 너비
DISPLAY_MAX_WIDTH   = 960       # 디버그 창 표시 너비


# ==================================================
# 2. 파일 경로 및 네트워크 설정
# ==================================================
# 모델 및 설정 파일 경로
CFG_PATH            = "/home/kaisys/detectron2/projects/PointRend/configs/InstanceSegmentation/pointrend_rcnn_R_50_FPN_3x_coco.yaml"
WEIGHTS_PATH        = "/home/kaisys/Project/대차인식WS_V1.pth"
CONFIG_INI_PATH     = "/home/kaisys/CheckWheelStatusPy/Config.ini"

# 비디오 / RTSP 입력
RTSP_URL            = "/home/kaisys/Project/program/output.avi"
RECONNECT_WAIT_SEC  = 2.0       # 재연결 대기 시간 (초)
USE_FFMPEG          = True
DROP_OLD_FRAMES     = True

# ZMQ 네트워크 송신
PUSH_BIND                 = "tcp://*:5577"
ZMQ_SNDHWM                = 1
ZMQ_QUEUE_MAXSIZE         = 1000
ZMQ_QUEUE_PUT_TIMEOUT_SEC = 0.01


# ==================================================
# 3. Detectron2 (AI 모델) 파라미터
# ==================================================
D2_MIN_SIZE_TEST      = 720
D2_MAX_SIZE_TEST      = 1280
D2_NUM_CLASSES        = 11
D2_SCORE_THRESH_TEST  = 0.8

D2_META_NAME          = "inference_meta_pointrend_numbers"
D2_MARK_CLASS_NAME    = "mark"

def get_device():
    return "cuda" if torch.cuda.is_available() else "cpu"


# ==================================================
# 4. 알고리즘 로직 설정 (상태 머신)
# ==================================================
DETECT_INTERVAL_FRAMES = 1
NO_DIGIT_END_FRAMES    = 5      # 숫자가 사라져도 N프레임 대기 후 종료 (끊김 방지)

ROI_Y_MIN_RATIO        = 0.40   # 관심 영역(ROI) 상단 비율
ROI_Y_MAX_RATIO        = 0.90   # 관심 영역(ROI) 하단 비율
EMPTY_CODE_OK          = True


# ==================================================
# 5. 공유 메모리 (Shared Memory) 설정
# ==================================================
SHM_NAME                = "wheel_status_mem"
SHM_SIZE                = 100
WHEEL_POLL_INTERVAL_SEC = 0.02  # 휠 감시 주기
SHM_MONITOR_POLL_SEC    = 0.05  # 모니터링 주기
SHM_MONITOR_RANGE       = 50


# ==================================================
# 6. 공유 메모리 주소 맵 (Memory Layout)
# ==================================================

# --- Common Area ---
IDX_STOP_FLAG    = 0
IDX_NEW_CAR_FLAG = 1
IDX_CAR_NO_0     = 2
IDX_CAR_NO_1     = 3
IDX_CAR_NO_2     = 4

# --- DS (Different Sensor) Area ---
# 1st Wheel
DS_FLAG_1        = 10
DS_CAR_1         = (11, 12, 13)
DS_ROT_1         = 16
DS_POS_1         = 17

# 2nd Wheel
DS_FLAG_2        = 20
DS_CAR_2         = (21, 22, 23)
DS_ROT_2         = 26
DS_POS_2         = 27

# --- WS (Wheel Sensor) Area ---
# 1st Wheel
WS_FLAG_1        = 30
WS_CAR_1         = (31, 32, 33)
WS_ROT_1         = 36
WS_POS_1         = 37

# 2nd Wheel
WS_FLAG_2        = 40
WS_CAR_2         = (41, 42, 43)
WS_ROT_2         = 46
WS_POS_2         = 47