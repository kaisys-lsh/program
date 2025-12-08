# run_sender.py
# --------------------------------------------------
# 메인 진입 파일
# TEST_IMAGE_MODE 가 True이면 이미지 폴더 버전,
# False 이면 RTSP 영상 버전 실행
# --------------------------------------------------

from config import config   
from setup.detectron_setup import setup_detectron
from utils.zmq_utils import make_zmq_sender
from utils.image_mode import run_image_mode
from utils.video_mode import run_video_mode

# True: 이미지 폴더, False: RTSP/영상
TEST_IMAGE_MODE = True


def main():
    predictor, metadata, mark_class_idx = setup_detectron()
    ctx, sock = make_zmq_sender()

    try:
        if TEST_IMAGE_MODE:
            print("[MAIN] TEST_IMAGE_MODE=True → 이미지 모드 실행")
            run_image_mode(predictor, metadata, mark_class_idx, ctx, sock)
        else:
            print("[MAIN] TEST_IMAGE_MODE=False → 영상 모드 실행")
            run_video_mode(predictor, metadata, mark_class_idx, ctx, sock)

    finally:
        try:
            sock.close()
        except:
            pass

        try:
            ctx.term()
        except:
            pass


if __name__ == "__main__":
    main()
