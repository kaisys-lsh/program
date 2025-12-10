# run_sender.py
# --------------------------------------------------
# Detectron2 번호 인식 + WS/DS 공유메모리 업데이트 + ZMQ 송신
# --------------------------------------------------

import time
import subprocess

from config import config
from setup.detectron_setup import setup_detectron
from utils.zmq_utils import make_zmq_sender
from mode.image_mode import run_image_mode
from mode.video_mode import run_video_mode

# 공유메모리
from utils.shared_mem_utils import open_or_create_shm

TEST_IMAGE_MODE = True


def main():

    # --------------------------------------------------
    # 1) Detectron2 번호 인식 준비
    # --------------------------------------------------
    predictor, metadata, mark_class_idx = setup_detectron()
    ctx, sock = make_zmq_sender()

    # --------------------------------------------------
    # 2) WS / DS 공유메모리 열기
    # --------------------------------------------------
    shm_ws = None
    shm_ds = None
    shm_ws_buf = None
    shm_ds_buf = None

    try:
        shm_ws, shm_ws_buf = open_or_create_shm(
            config.SHM_WS_NAME, config.SHM_SIZE
        )
        print("[SHM] WS shm opened")
    except Exception as e:
        print("[SHM] WS shared memory error:", e)

    try:
        shm_ds, shm_ds_buf = open_or_create_shm(
            config.SHM_DS_NAME, config.SHM_SIZE
        )
        print("[SHM] DS shm opened")
    except Exception as e:
        print("[SHM] DS shared memory error:", e)

    # --------------------------------------------------
    # 3) 번호 인식 메인 루프 실행
    # --------------------------------------------------
    try:
        if TEST_IMAGE_MODE:
            print("[MAIN] 이미지 모드 실행")
            run_image_mode(
                predictor,
                metadata,
                mark_class_idx,
                ctx,
                sock,
                shm_ws_buf,
                shm_ds_buf,
            )
        else:
            print("[MAIN] 영상 모드 실행")
            run_video_mode(
                predictor,
                metadata,
                mark_class_idx,
                ctx,
                sock,
                shm_ws_buf,
                shm_ds_buf,
            )

    finally:
        # --------------------------------------------------
        # 종료 처리
        # --------------------------------------------------
        try: sock.close()
        except: pass

        try: ctx.term()
        except: pass

        try:
            if shm_ws: shm_ws.close()
        except: pass

        try:
            if shm_ds: shm_ds.close()
        except: pass


if __name__ == "__main__":
    main()
