# mode/video_mode.py
# --------------------------------------------------
# RTSP 기반 대차번호 인식
# - 번호만 공유메모리에 전달
# --------------------------------------------------

import time
import cv2
import torch

from config import config
from utils.digit_utils import filter_digit_region, build_code_if_exact_3
from utils.shared_mem_utils import write_car_number


def open_capture(url):
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG if config.USE_FFMPEG else 0)
    if not cap.isOpened():
        return None
    for _ in range(3):
        cap.read()
    return cap


def run_video_mode(predictor, metadata, mark_class_idx, car_bus, shm_ws_array, shm_ds_array):
    frame_interval = 1.0 / config.FPS if config.FPS > 0 else 1.0
    cap = None

    mark_ready = False
    in_wagon = False
    no_digit_frames = 0
    best_final_code = "NONE"

    print("[VIDEO MODE] start")

    while True:
        if cap is None or not cap.isOpened():
            cap = open_capture(config.RTSP_URL)
            if cap is None:
                time.sleep(config.RECONNECT_WAIT_SEC)
                continue

        t0 = time.time()
        ret, img = cap.read()
        if not ret or img is None:
            cap.release()
            cap = None
            continue

        img_h, img_w = img.shape[:2]
        run_detect = True

        send_start = False
        send_end_code = None

        if run_detect:
            with torch.inference_mode():
                outputs = predictor(img)
            instances = outputs["instances"].to("cpu")

            mark_present = False
            if len(instances) > 0 and mark_class_idx is not None:
                mask_mark = (instances.pred_classes == mark_class_idx)
                mark_present = mask_mark.any()
                num_instances = instances[~mask_mark]
            else:
                num_instances = instances

            num_instances = filter_digit_region(num_instances, img_h, img_w)

            if not in_wagon:
                if (not mark_ready) and mark_present:
                    mark_ready = True
                if mark_ready and len(num_instances) > 0:
                    in_wagon = True
                    no_digit_frames = 0
                    best_final_code = "NONE"
                    send_start = True
            else:
                if len(num_instances) == 0:
                    no_digit_frames += 1
                else:
                    no_digit_frames = 0
                    code = build_code_if_exact_3(num_instances, metadata)
                    if code != "NONE":
                        best_final_code = code

                if no_digit_frames >= config.NO_DIGIT_END_FRAMES:
                    send_end_code = best_final_code
                    in_wagon = False
                    mark_ready = False
                    no_digit_frames = 0
                    best_final_code = "NONE"

            del outputs, instances, num_instances

        if send_start:
            car_bus.send_start()

        if send_end_code is not None:
            code = send_end_code if send_end_code != "NONE" else "FFF"

            if shm_ws_array is not None:
                write_car_number(shm_ws_array, code, block=False)
            if shm_ds_array is not None:
                write_car_number(shm_ds_array, code, block=False)

            car_bus.send_end(code)

        elapsed = time.time() - t0
        if frame_interval - elapsed > 0:
            time.sleep(frame_interval - elapsed)
