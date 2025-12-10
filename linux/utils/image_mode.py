# utils/image_mode.py
# --------------------------------------------------
# 폴더 이미지 버전 루프
# (처음에 리팩토링한 run_sender.py 로직 그대로)
# --------------------------------------------------

import time
import cv2
import torch

from config import config 
from utils.image_utils import get_image_paths
from utils.digit_utils import (
    filter_digit_region,
    init_slots,
    update_slots_with_instances,
    build_final_code_from_slots,
    decode_label_char,
)


def run_image_mode(predictor, metadata, mark_class_idx, ctx, sock):
    # FPS 제어용
    if config.FPS > 0:
        frame_interval = 1.0 / config.FPS
    else:
        frame_interval = 1.0

    use_cuda = torch.cuda.is_available()

    # 이미지 목록 읽기
    image_paths = get_image_paths(config.IMAGE_DIR)

    if len(image_paths) == 0:
        print("[ERROR] No images found in", config.IMAGE_DIR)
        return

    print("[IMAGE MODE] IMAGE_DIR:", config.IMAGE_DIR,
          ", num_images =", len(image_paths),
          ", FPS =", config.FPS,
          ", CUDA =", use_cuda)

    # 상태 변수들
    frame_idx = 0           # 전체 프레임 번호
    img_idx = 0             # 이미지 리스트 인덱스 (순환)

    mark_ready = False      # mark 를 본 뒤 숫자를 기다리는 상태인지
    in_wagon = False        # 현재 대차 번호 수집 중인지(START 이후)
    no_digit_frames = 0     # in_wagon 상태에서 연속 숫자 미검출 프레임 수
    slots = init_slots()    # 100,10,1 자리 숫자 정보 저장용

    try:
        while True:
            t0 = time.time()

            # 이미지 하나 선택 (순환)
            img_path = image_paths[img_idx]
            img_idx = img_idx + 1
            if img_idx >= len(image_paths):
                img_idx = 0

            img = cv2.imread(img_path)
            if img is None:
                print("[WARN] failed to read image:", img_path)
                continue

            # 원래 코드와 맞추기 위해 960x540 으로 리사이즈
            img = cv2.resize(img, (960, 540))
            img_h, img_w = img.shape[0], img.shape[1]

            # 이 프레임에서 추론을 할지 여부
            run_detect = False
            if frame_idx % config.DETECT_INTERVAL_FRAMES == 0:
                run_detect = True

            send_code = ""

            if run_detect:
                # 추론
                with torch.inference_mode():
                    outputs = predictor(img)

                instances = outputs["instances"].to("cpu")

                # mark / 숫자 분리
                mark_present = False
                mark_instances = None

                if len(instances) > 0:
                    if mark_class_idx is not None:
                        # mark 인 것과 아닌 것을 나눔
                        mask_mark = (instances.pred_classes == mark_class_idx)

                        if mask_mark.any():
                            mark_present = True
                            mark_idxs = torch.nonzero(mask_mark).squeeze(1)
                            mark_instances = instances[mark_idxs]

                        # mark 가 아닌 것들은 숫자
                        mask_not_mark = ~mask_mark
                        num_instances = instances[mask_not_mark]
                    else:
                        # mark 클래스 index 를 못 찾았으면 전부 숫자로 간주
                        num_instances = instances
                else:
                    num_instances = instances

                # 숫자 영역 필터링 (잡음 제거)
                num_instances = filter_digit_region(num_instances, img_h, img_w)

                # 화면에 숫자 검출 결과 그리기 (디버깅용)
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

                    i += 1

                # mark 박스도 보고 싶다면 빨간색으로 그리기
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

                        j += 1

                # -------------------------------
                # 상태 머신 (mark / START / END)
                # -------------------------------

                # 1) 아직 대차 구간이 아닐 때 (in_wagon == False)
                if not in_wagon:
                    # mark 를 처음 보면 mark_ready 플래그 켜기
                    if (not mark_ready) and mark_present:
                        mark_ready = True

                    # mark 를 본 뒤에 숫자가 나오면 START
                    if mark_ready and len(num_instances) > 0:
                        in_wagon = True
                        slots = init_slots()
                        no_digit_frames = 0
                        send_code = "START"
                        print("[WAGON] START")

                # 2) 대차 번호 수집 중일 때 (in_wagon == True)
                if in_wagon:
                    if len(num_instances) == 0:
                        # 숫자가 안 보임 → 카운터 증가
                        no_digit_frames = no_digit_frames + 1
                    else:
                        # 숫자가 보이면 카운터 초기화하고 슬롯 업데이트
                        no_digit_frames = 0
                        update_slots_with_instances(slots, num_instances, metadata)

                    # 연속으로 숫자가 안 보인 프레임 수가 기준 이상이면 END
                    if no_digit_frames >= config.NO_DIGIT_END_FRAMES:
                        final_code = build_final_code_from_slots(slots)
                        send_code = final_code
                        print("[WAGON] END →", final_code)

                        # 상태 초기화
                        in_wagon = False
                        mark_ready = False
                        slots = init_slots()
                        no_digit_frames = 0

                # 메모리 정리
                del outputs
                del instances
                del num_instances

            # JPEG 인코딩
            ok, jpg_buf = cv2.imencode(
                ".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), config.JPEG_QUALITY]
            )

            if not ok:
                frame_idx = frame_idx + 1
                continue

            # ZMQ 로 전송
            if send_code or config.EMPTY_CODE_OK:
                if send_code:
                    code_bytes = send_code.encode("utf-8")
                else:
                    code_bytes = b""

                sock.send_multipart([code_bytes, jpg_buf.tobytes()])

                if send_code:
                    print("[SEND] code='{}'".format(send_code))

            # FPS 맞추기
            elapsed = time.time() - t0
            remain = frame_interval - elapsed
            if remain > 0:
                time.sleep(remain)

            frame_idx = frame_idx + 1

    except KeyboardInterrupt:
        print("\n[IMAGE MODE] KeyboardInterrupt -> 종료")
