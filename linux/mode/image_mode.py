# mode/image_mode.py
# --------------------------------------------------
# 폴더 이미지 기반 대차번호 인식
# - 번호 인식 결과만 공유메모리에 전달
# - 휠상태 로직은 관여하지 않음
# --------------------------------------------------

import time
import cv2
import torch

from config import config
from utils.image_utils import get_image_paths
from utils.digit_utils import filter_digit_region, build_code_if_exact_3
from utils.shared_mem_utils import write_car_number


def run_image_mode(predictor, metadata, mark_class_idx, car_bus, shm_ws_array, shm_ds_array):
    frame_interval = 1.0 / config.FPS if config.FPS > 0 else 1.0

    image_paths = get_image_paths(config.IMAGE_DIR)
    if not image_paths:
        print("[IMAGE MODE] no images")
        return

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

        # ---- 이벤트 / 공유메모리 ----
        if send_start:
            car_bus.send_start()

        if send_end_code is not None:
            # 3자리 아니면 FFF
            code = send_end_code if send_end_code != "NONE" else "FFF"

            if shm_ws_array is not None:
                write_car_number(shm_ws_array, code, block=False)
            if shm_ds_array is not None:
                write_car_number(shm_ds_array, code, block=False)

            car_bus.send_end(code)

        elapsed = time.time() - t0
        if frame_interval - elapsed > 0:
            time.sleep(frame_interval - elapsed)

        frame_idx += 1
