# utils/video_mode.py
# --------------------------------------------------
# RTSP / HTTP 영상 버전 루프
# 원래 이미지 버전과 동일한 상태 머신 / 슬롯 로직 사용
# --------------------------------------------------

import time
import cv2
import torch

from config import config
from utils.digit_utils import (
    filter_digit_region,
    init_slots,
    update_slots_with_instances,
    build_final_code_from_slots,
    decode_label_char,
)

# ★ 공유메모리 유틸 추가
from utils.shared_mem_utils import get_shared_memory, write_car_number


def open_capture(url):
    """
    RTSP/HTTP 캡처 열기 (DROP_OLD_FRAMES 적용)
    """
    if config.USE_FFMPEG:
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    else:
        cap = cv2.VideoCapture(url)

    if config.DROP_OLD_FRAMES:
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except:
            pass

    if not cap.isOpened():
        return None

    # 초기 몇 프레임 버리기 (버퍼 비우기)
    n = 0
    while n < 3:
        cap.read()
        n = n + 1

    return cap


def run_video_mode(predictor, metadata, mark_class_idx, ctx, sock, shm_ws_array, shm_ds_array):
    """
    RTSP_URL 에서 영상 프레임을 읽어서
    동일한 상태 머신으로 처리.
    + 번호 인식이 끝났을 때 WS/DS 공유메모리에 번호 3자리 기록.
    + ZMQ로는 '번호 문자열만' 전송 (START / 3자리 / NONE)
    """
    if config.FPS > 0:
        frame_interval = 1.0 / config.FPS
    else:
        frame_interval = 1.0

    use_cuda = torch.cuda.is_available()

    # ★ WS / DS 공유메모리 두 개 모두 연다.
    shm_ws = None
    shm_ds = None
    status_ws = None
    status_ds = None
    try:
        shm_ws, status_ws = get_shared_memory("WS_POS")
    except Exception as e:
        print("[SHM] WS_POS 공유메모리 초기화 실패:", e)

    try:
        shm_ds, status_ds = get_shared_memory("DS_POS")
    except Exception as e:
        print("[SHM] DS_POS 공유메모리 초기화 실패:", e)

    cap = None

    print("[VIDEO MODE] RTSP:", config.RTSP_URL,
          ", FPS =", config.FPS,
          ", CUDA =", use_cuda)

    frame_idx = 0
    mark_ready = False
    in_wagon = False
    no_digit_frames = 0
    slots = init_slots()

    try:
        while True:
            # 캡처 준비 / 재연결
            if cap is None or not cap.isOpened():
                print("[RTSP] connecting...")
                cap = open_capture(config.RTSP_URL)
                if cap is None:
                    print("[RTSP] open failed")
                    time.sleep(config.RECONNECT_WAIT_SEC)
                    continue
                print("[RTSP] connected")

            t0 = time.time()

            ret, img = cap.read()
            if not ret or img is None:
                print("[RTSP] read failed → reconnect")
                try:
                    cap.release()
                except:
                    pass
                cap = None
                time.sleep(config.RECONNECT_WAIT_SEC)
                continue

            img = cv2.resize(img, (960, 540))
            img_h, img_w = img.shape[0], img.shape[1]

            run_detect = (frame_idx % config.DETECT_INTERVAL_FRAMES == 0)

            send_code = ""

            if run_detect:
                with torch.inference_mode():
                    outputs = predictor(img)
                instances = outputs["instances"].to("cpu")

                mark_present = False
                mark_instances = None

                if len(instances) > 0:
                    if mark_class_idx is not None:
                        mask_mark = (instances.pred_classes == mark_class_idx)

                        if mask_mark.any():
                            mark_present = True
                            mark_idxs = torch.nonzero(mask_mark).squeeze(1)
                            mark_instances = instances[mark_idxs]

                        mask_not_mark = ~mask_mark
                        num_instances = instances[mask_not_mark]
                    else:
                        num_instances = instances
                else:
                    num_instances = instances

                # 숫자 영역 필터링 (잡음 제거)
                num_instances = filter_digit_region(num_instances, img_h, img_w)

                # -------------------------------
                # 상태 머신 (mark / START / END)
                # -------------------------------
                if not in_wagon:
                    if (not mark_ready) and mark_present:
                        mark_ready = True

                    if mark_ready and len(num_instances) > 0:
                        in_wagon = True
                        slots = init_slots()
                        no_digit_frames = 0
                        send_code = "START"
                        print("[WAGON] START")

                else:
                    if len(num_instances) == 0:
                        no_digit_frames += 1
                    else:
                        no_digit_frames = 0
                        update_slots_with_instances(slots, num_instances, metadata)

                    if no_digit_frames >= config.NO_DIGIT_END_FRAMES:
                        final_code = build_final_code_from_slots(slots)
                        send_code = final_code
                        print("[WAGON] END →", final_code)

                        # 공유메모리 기록
                        if final_code != "NONE":
                            if shm_ws_array is not None:
                                write_car_number(shm_ws_array, final_code, block=False)
                            if shm_ds_array is not None:
                                write_car_number(shm_ds_array, final_code, block=False)

                        # 상태 초기화
                        in_wagon = False
                        mark_ready = False
                        slots = init_slots()
                        no_digit_frames = 0

                # 메모리 정리
                del outputs
                del instances
                del num_instances
                del mark_instances

            # ✅ 번호만 ZMQ로 전송 (빈 메시지 안 보냄)
            if send_code:
                sock.send_string(send_code)  # "START" / "123" / "NONE"
                print("[SEND] code='{}'".format(send_code))

            # FPS 맞추기
            elapsed = time.time() - t0
            remain = frame_interval - elapsed
            if remain > 0:
                time.sleep(remain)

            frame_idx += 1

    except KeyboardInterrupt:
        print("\n[VIDEO MODE] KeyboardInterrupt -> 종료")

    finally:
        try:
            if cap is not None:
                cap.release()
        except:
            pass

        try:
            if shm_ws is not None:
                shm_ws.close()
        except:
            pass

        try:
            if shm_ds is not None:
                shm_ds.close()
        except:
            pass
