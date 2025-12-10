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


def run_video_mode(predictor, metadata, mark_class_idx, ctx, sock,shm_ws_array, shm_ds_array):
    """
    RTSP_URL 에서 영상 프레임을 읽어서
    이미지 버전과 동일한 상태 머신으로 처리.
    + 번호 인식이 끝났을 때 WS/DS 공유메모리에 번호 3자리 기록.
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

            run_detect = False
            if frame_idx % config.DETECT_INTERVAL_FRAMES == 0:
                run_detect = True

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

                num_instances = filter_digit_region(num_instances, img_h, img_w)

                i = 0
                while i < len(num_instances):
                    box_tensor = num_instances.pred_boxes.tensor[i]
                    box = box_tensor.numpy().astype(int)

                    x1 = int(box[0])
                    y1 = int(box[1])
                    x2 = int(box[2])
                    y2 = int(box[3])

                    cls_id = int(num_instances.pred_classes[i])
                    ch = decode_label_char(cls_id, metadata)

                    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(
                        img,
                        ch,
                        (x1, max(y1 - 10, 20)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1.2,
                        (0, 255, 0),
                        2,
                    )

                    i = i + 1

                if mark_instances is not None:
                    j = 0
                    while j < len(mark_instances):
                        box_tensor = mark_instances.pred_boxes.tensor[j]
                        box = box_tensor.numpy().astype(int)

                        x1 = int(box[0])
                        y1 = int(box[1])
                        x2 = int(box[2])
                        y2 = int(box[3])

                        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
                        cv2.putText(
                            img,
                            "M",
                            (x1, max(y1 - 10, 20)),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            1.2,
                            (0, 0, 255),
                            2,
                        )

                        j = j + 1

                # ---- 여기부터 상태 머신은 이미지 버전과 완전히 동일 ----

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
                        no_digit_frames = no_digit_frames + 1
                    else:
                        no_digit_frames = 0
                        update_slots_with_instances(slots, num_instances, metadata)

                    if no_digit_frames >= config.NO_DIGIT_END_FRAMES:
                        final_code = build_final_code_from_slots(slots)
                        send_code = final_code
                        print("[WAGON] END →", final_code)

                        # ───────────────────────────────
                        # 🔹 대차 번호를 WS / DS 공유메모리에 기록
                        # ───────────────────────────────
                        if final_code != "NONE":
                            if shm_ws_array is not None:
                                write_car_number(
                                    shm_ws_array,
                                    final_code,
                                    block=False
                                )
                            if shm_ds_array is not None:
                                write_car_number(
                                    shm_ds_array,
                                    final_code,
                                    block=False
                                )

                        in_wagon = False
                        mark_ready = False
                        slots = init_slots()
                        no_digit_frames = 0


                del outputs
                del instances
                del num_instances

            ok, jpg_buf = cv2.imencode(
                ".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), config.JPEG_QUALITY]
            )
            if not ok:
                frame_idx = frame_idx + 1
                continue

            if send_code or config.EMPTY_CODE_OK:
                if send_code:
                    code_bytes = send_code.encode("utf-8")
                else:
                    code_bytes = b""

                sock.send_multipart([code_bytes, jpg_buf.tobytes()])

                if send_code:
                    print("[SEND] code='{}'".format(send_code))

            elapsed = time.time() - t0
            remain = frame_interval - elapsed
            if remain > 0:
                time.sleep(remain)

            frame_idx = frame_idx + 1

    except KeyboardInterrupt:
        print("\n[VIDEO MODE] KeyboardInterrupt -> 종료")

    finally:
        try:
            if cap is not None:
                cap.release()
        except:
            pass

        # ★ 공유메모리는 close만 하고 unlink는 하지 않는다.
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
