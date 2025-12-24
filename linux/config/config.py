# config.py

import torch

IMAGE_DIR     = "/home/kaisys/Project/image"
FPS           = 0.8
JPEG_QUALITY  = 80

TEST_IMAGE_MODE = True

CFG_PATH      = "/home/kaisys/detectron2/projects/PointRend/configs/InstanceSegmentation/pointrend_rcnn_R_50_FPN_3x_coco.yaml"
WEIGHTS_PATH  = "/home/kaisys/Project/대차인식WS_V1.pth"

PUSH_BIND     = "tcp://*:5577"
EMPTY_CODE_OK = True

DETECT_INTERVAL_FRAMES = 1
NO_DIGIT_END_FRAMES    = 2
ROI_Y_MIN_RATIO        = 0.40
ROI_Y_MAX_RATIO        = 0.90

# ── 여기부터 영상(RTSP)용 추가 ──
RTSP_URL           = "http://127.0.0.1:8000/video"  # 필요하면 RTSP URL로 변경
RECONNECT_WAIT_SEC = 2.0
USE_FFMPEG         = True
DROP_OLD_FRAMES    = True


def get_device():
    if torch.cuda.is_available():
        return "cuda"
    else:
        return "cpu"


# ─────────────────────────────────────────
# 🔹 대차번호를 쓰기 위한 공유메모리 설정 (WS / DS 공용)
#   → Wheel 상태 코드(Config.ini)랑 이름/크기 맞춰야 함
# ─────────────────────────────────────────
SHM_NAME = "wheel_status_mem"   
SHM_SIZE    = 100                 
