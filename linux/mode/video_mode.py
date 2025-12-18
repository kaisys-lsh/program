# mode/video_mode.py
import time
import cv2
import torch

from config import config
from utils.digit_utils import (
    filter_digit_region,
    build_code_if_exact_3,
)
from utils.shared_mem_utils import write_car_number


def open_capture(url):
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

    for _ in range(3):
        cap.read()
    return cap


def run_video_mode(predictor, metadata, mark_class_idx, car_bus, shm_ws_array, shm_ds_array):
    if config.FPS > 0:
        frame_interval = 1.0 / config.FPS
    else:
        frame_interval = 1.0

    use_cuda = torch.cuda.is_available()
    cap = None

    print("[VIDEO MODE] RTSP:", config.RTSP_URL,
          ", FPS =", config.FPS,
          ", CUDA =", use_cuda)

    frame_idx = 0
    mark_ready = False
    in_wagon = False
    no_digit_frames = 0

    # ✅ 이번 대차 구간에서 확실한 3자리가 한번이라도 나오면 저장
    best_final_code = "NONE"

    try:
        while True:
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

                else:
                    if len(num_instances) == 0:
                        no_digit_frames += 1
                    else:
                        no_digit_frames = 0

                        # ✅ 슬롯 대신: "확실한 3개면" 코드로 확정
                        code = build_code_if_exact_3(num_instances, metadata)
                        if code != "NONE":
                            best_final_code = code

                    if no_digit_frames >= config.NO_DIGIT_END_FRAMES:
                        send_end_code = best_final_code
                        print("[WAGON] END →", send_end_code)

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
        print("\n[VIDEO MODE] KeyboardInterrupt -> 종료")

    finally:
        try:
            if cap is not None:
                cap.release()
        except:
            pass
