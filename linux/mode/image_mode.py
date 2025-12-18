# mode/image_mode.py
# --------------------------------------------------
# 폴더 이미지 버전 루프 (3단계)
# - digit_utils: build_code_if_exact_3() 기반
# - car_event JSON 통일 (CarEventBus 사용)
# --------------------------------------------------

import time
import cv2
import torch

from config import config
from utils.image_utils import get_image_paths
from utils.digit_utils import (
    filter_digit_region,
    build_code_if_exact_3,
)

from utils.shared_mem_utils import write_car_number


def run_image_mode(predictor, metadata, mark_class_idx, car_bus, shm_ws_array, shm_ds_array):
    if config.FPS > 0:
        frame_interval = 1.0 / config.FPS
    else:
        frame_interval = 1.0

    use_cuda = torch.cuda.is_available()

    image_paths = get_image_paths(config.IMAGE_DIR)
    if len(image_paths) == 0:
        print("[ERROR] No images found in", config.IMAGE_DIR)
        return

    print("[IMAGE MODE] IMAGE_DIR:", config.IMAGE_DIR,
          ", num_images =", len(image_paths),
          ", FPS =", config.FPS,
          ", CUDA =", use_cuda)

    frame_idx = 0
    img_idx = 0

    mark_ready = False
    in_wagon = False
    no_digit_frames = 0

    # ✅ 이번 대차 구간에서 "확실한 3자리"가 나온 적 있으면 저장
    best_final_code = "NONE"

    try:
        while True:
            t0 = time.time()

            img_path = image_paths[img_idx]
            img_idx += 1
            if img_idx >= len(image_paths):
                img_idx = 0

            img = cv2.imread(img_path)
            if img is None:
                print("[WARN] failed to read image:", img_path)
                continue

            img = cv2.resize(img, (960, 540))
            img_h, img_w = img.shape[0], img.shape[1]

            run_detect = (frame_idx % config.DETECT_INTERVAL_FRAMES == 0)

            send_start = False
            send_end_code = None

            if run_detect:
                with torch.inference_mode():
                    outputs = predictor(img)

                instances = outputs["instances"].to("cpu")

                mark_present = False
                if len(instances) > 0:
                    if mark_class_idx is not None:
                        mask_mark = (instances.pred_classes == mark_class_idx)
                        if mask_mark.any():
                            mark_present = True
                        num_instances = instances[~mask_mark]
                    else:
                        num_instances = instances
                else:
                    num_instances = instances

                num_instances = filter_digit_region(num_instances, img_h, img_w)

                # -------------------------------
                # 상태 머신 (mark / START / END)
                # -------------------------------
                if not in_wagon:
                    if (not mark_ready) and mark_present:
                        mark_ready = True

                    if mark_ready and len(num_instances) > 0:
                        in_wagon = True
                        no_digit_frames = 0
                        best_final_code = "NONE"
                        send_start = True
                        print("[WAGON] START")

                if in_wagon:
                    if len(num_instances) == 0:
                        no_digit_frames += 1
                    else:
                        no_digit_frames = 0

                        # ✅ 슬롯 대신: "확실한 3개면" 즉시 코드로 변환
                        code = build_code_if_exact_3(num_instances, metadata)
                        if code != "NONE":
                            best_final_code = code

                    if no_digit_frames >= config.NO_DIGIT_END_FRAMES:
                        send_end_code = best_final_code
                        print("[WAGON] END →", send_end_code)

                        # 공유메모리 기록 (성공일 때만)
                        if send_end_code != "NONE":
                            if shm_ws_array is not None:
                                write_car_number(shm_ws_array, send_end_code, block=False)
                            if shm_ds_array is not None:
                                write_car_number(shm_ds_array, send_end_code, block=False)

                        in_wagon = False
                        mark_ready = False
                        no_digit_frames = 0
                        best_final_code = "NONE"

                del outputs, instances, num_instances

            # ✅ JSON 이벤트 전송
            if send_start:
                car_bus.send_start()

            if send_end_code is not None:
                car_bus.send_end(send_end_code)

            elapsed = time.time() - t0
            remain = frame_interval - elapsed
            if remain > 0:
                time.sleep(remain)

            frame_idx += 1

    except KeyboardInterrupt:
        print("\n[IMAGE MODE] KeyboardInterrupt -> 종료")
