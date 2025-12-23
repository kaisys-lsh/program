# mode/car_number_mode.py
# --------------------------------------------------
# 대차번호 인식 (IMAGE / VIDEO 모드 통합)
# - TEST_IMAGE_MODE(True/False)로 모드 선택
# - 번호만 공유메모리에 전달 (flag(1) 프로토콜 준수)
# --------------------------------------------------

import time
import cv2
import torch

from config import config
from utils.digit_utils import filter_digit_region, build_code_if_exact_3
from utils.shared_mem_utils import write_car_number


# -----------------------------
# VIDEO(RTSP)용
# -----------------------------
def open_capture(url):
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG if config.USE_FFMPEG else 0)
    if not cap.isOpened():
        return None
    for _ in range(3):
        cap.read()
    return cap


def _handle_end_code(car_bus, shm_ws_array, shm_ds_array, send_end_code):
    # 3자리 아니면 FFF
    code = send_end_code if send_end_code != "NONE" else "FFF"

    # flag(1)==0일 때만 쓰고, 아니면 잠깐 기다렸다가(최대 1초) 쓰기
    if shm_ws_array is not None:
        ok_ws = write_car_number(shm_ws_array, code, block=True, timeout_sec=1.0, poll_interval=0.02)
        print("[SHM] WS write ok?", ok_ws, "code=", code)

    if shm_ds_array is not None:
        ok_ds = write_car_number(shm_ds_array, code, block=True, timeout_sec=1.0, poll_interval=0.02)
        print("[SHM] DS write ok?", ok_ds, "code=", code)

    # ZMQ 이벤트는 "인식한 코드"를 그대로 END에 실어 보냄
    # (공유메모리는 FFF로 fallback 되었을 수도 있으니, UI는 ZMQ를 보게 할 거면 이것도 동일하게 보내고 싶다면 여기서 code를 쓰면 됨)
    car_bus.send_end(code)


# -----------------------------
# IMAGE(JPG 폴더) 모드
# -----------------------------
def run_image_mode(predictor, metadata, mark_class_idx, car_bus, shm_ws_array, shm_ds_array):
    from utils.image_utils import get_image_paths
    from detectron2.utils.visualizer import Visualizer

    frame_interval = 1.0 / config.FPS if config.FPS > 0 else 1.0

    image_paths = get_image_paths(config.IMAGE_DIR)
    if not image_paths:
        print("[IMAGE MODE] no images")
        return

    SHOW_WIN = True
    WIN_NAME = "DETECT"
    last_show = None

    frame_idx = 0
    img_idx = 0

    mark_ready = False
    in_wagon = False
    no_digit_frames = 0
    best_final_code = "NONE"

    print("[IMAGE MODE] start")

    while True:
        t0 = time.time()

        img = cv2.imread(image_paths[img_idx])
        img_idx = (img_idx + 1) % len(image_paths)
        if img is None:
            continue

        img = cv2.resize(img, (960, 540))
        img_h, img_w = img.shape[:2]

        run_detect = (frame_idx % config.DETECT_INTERVAL_FRAMES == 0)
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

            if SHOW_WIN:
                vis = Visualizer(img[:, :, ::-1], metadata=metadata, scale=1.0)
                vis_out = vis.draw_instance_predictions(num_instances)  # 숫자만 표시
                last_show = vis_out.get_image()[:, :, ::-1]  # BGR

            # ---- 상태 머신 ----
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

        if SHOW_WIN:
            if last_show is None:
                last_show = img
            cv2.imshow(WIN_NAME, last_show)
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):  # ESC or q
                cv2.destroyAllWindows()
                return

        # ---- 이벤트 / 공유메모리 ----
        if send_start:
            car_bus.send_start()

        if send_end_code is not None:
            _handle_end_code(car_bus, shm_ws_array, shm_ds_array, send_end_code)

        elapsed = time.time() - t0
        if frame_interval - elapsed > 0:
            time.sleep(frame_interval - elapsed)

        frame_idx += 1


# -----------------------------
# VIDEO(RTSP) 모드
# -----------------------------
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

        send_start = False
        send_end_code = None

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

        # ---- 상태 머신 ----
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
            _handle_end_code(car_bus, shm_ws_array, shm_ds_array, send_end_code)

        elapsed = time.time() - t0
        if frame_interval - elapsed > 0:
            time.sleep(frame_interval - elapsed)


# -----------------------------
# Wrapper: TEST_IMAGE_MODE로 선택
# -----------------------------
def run_car_number_mode(use_image_mode, predictor, metadata, mark_class_idx, car_bus, shm_ws_array, shm_ds_array):
    if use_image_mode:
        run_image_mode(predictor, metadata, mark_class_idx, car_bus, shm_ws_array, shm_ds_array)
    else:
        run_video_mode(predictor, metadata, mark_class_idx, car_bus, shm_ws_array, shm_ds_array)
