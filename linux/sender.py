# sender_folder_push_vote_slot.py
import os, time, cv2, zmq, torch, gc, glob, re
import numpy as np
from datetime import datetime

from detectron2.config import get_cfg
from detectron2.engine import DefaultPredictor
from detectron2.data import MetadataCatalog
from detectron2.projects import point_rend

# ─────────────────────────────────────────────
# [환경설정]
# ─────────────────────────────────────────────
IMAGE_DIR     = "/home/kaisys/Project/image"
FPS           = 2
JPEG_QUALITY  = 80

CFG_PATH      = "/home/kaisys/detectron2/projects/PointRend/configs/InstanceSegmentation/pointrend_rcnn_R_50_FPN_3x_coco.yaml"
WEIGHTS_PATH  = "/home/kaisys/Project/대차인식WS_V1.pth"

PUSH_BIND     = "tcp://*:5577"

EMPTY_CODE_OK = True

# 새 로직 파라미터
DETECT_INTERVAL_FRAMES = 2      # 2프레임당 1번 추론
NO_DIGIT_END_FRAMES    = 4      # 연속 4번 숫자 미검출 → END
ROI_Y_MIN_RATIO        = 0.40   # 숫자가 나오는 대략적인 세로 위치 (이미지 높이 비율)
ROI_Y_MAX_RATIO        = 0.90

# ─────────────────────────────────────────────
# 유틸: 이미지 파일 정렬용 (이름에 들어 있는 숫자 기준)
# ─────────────────────────────────────────────
def numeric_sort_key(path):
    name = os.path.basename(path)
    m = re.search(r'\d+', name)
    if m:
        return int(m.group())
    return name

# ─────────────────────────────────────────────
# Detectron2 설정
# ─────────────────────────────────────────────
def setup_detectron():
    cfg = get_cfg()
    point_rend.add_pointrend_config(cfg)
    cfg.merge_from_file(CFG_PATH)
    cfg.MODEL.WEIGHTS = WEIGHTS_PATH

    cfg.INPUT.MIN_SIZE_TEST = 720
    cfg.INPUT.MAX_SIZE_TEST = 1280
    cfg.MODEL.ROI_HEADS.NUM_CLASSES = 11
    cfg.MODEL.POINT_HEAD.NUM_CLASSES = 11
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = 0.8
    cfg.MODEL.DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

    metadata = None
    mark_class_idx = None

    try:
        ckpt = torch.load(WEIGHTS_PATH, map_location="cpu")
        meta_name = "inference_meta_pointrend_numbers"
        MetadataCatalog.get(meta_name).set(**ckpt.get("metadata", {}))
        metadata = MetadataCatalog.get(meta_name)

        if metadata is not None and hasattr(metadata, "thing_classes"):
            for i, name in enumerate(metadata.thing_classes):
                if str(name).lower() == "mark":
                    mark_class_idx = i
                    print(f"[META] mark class idx = {mark_class_idx}")
                    break

    except Exception as e:
        print("[WARN] metadata load failed:", e)
        metadata = None

    predictor = DefaultPredictor(cfg)
    return predictor, metadata, mark_class_idx

# ─────────────────────────────────────────────
# ZMQ Sender
# ─────────────────────────────────────────────
def make_zmq_sender():
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.PUSH)
    sock.setsockopt(zmq.SNDHWM, 1)
    sock.bind(PUSH_BIND)
    print(f"[PUSH] bind {PUSH_BIND}")
    time.sleep(0.5)
    return ctx, sock

# ─────────────────────────────────────────────
# 숫자 / 마크 관련 유틸
# ─────────────────────────────────────────────
def decode_label_char(cls_id, metadata):
    """
    클래스 id -> 한 자리 문자로 변환.
    thing_classes 가 있다면 라벨의 마지막 글자를 사용, 없으면 id 그대로.
    """
    label = ""
    if metadata is not None and hasattr(metadata, "thing_classes"):
        if 0 <= cls_id < len(metadata.thing_classes):
            label = metadata.thing_classes[cls_id]

    if not label:
        label = str(cls_id)

    # "num_3" 이면 '3' 사용
    ch = (label[-1] if label else "0")[0]
    return ch

def filter_digit_region(instances, img_h, img_w):
    """
    위쪽 잡문자/오검을 줄이기 위해 숫자가 나오는 대략적인 세로/크기 범위로 필터링.
    """
    if len(instances) == 0:
        return instances

    boxes = instances.pred_boxes.tensor.numpy()
    yc = (boxes[:, 1] + boxes[:, 3]) * 0.5
    h  = boxes[:, 3] - boxes[:, 1]

    # 세로 위치 필터
    mask_y = (yc >= img_h * ROI_Y_MIN_RATIO) & (yc <= img_h * ROI_Y_MAX_RATIO)

    # 높이 기반 필터 (너무 작거나 큰 것 제거)
    h_mean = h.mean()
    if h_mean > 0:
        mask_h = (h >= h_mean * 0.5) & (h <= h_mean * 1.8)
    else:
        mask_h = np.ones_like(h, dtype=bool)

    keep = mask_y & mask_h
    if not keep.any():
        # 전부 걸러진 경우 빈 Instances 반환
        return instances[[]]

    keep_idx = torch.from_numpy(np.nonzero(keep)[0]).to(instances.pred_boxes.device)
    return instances[keep_idx]

def sort_by_x(instances):
    if len(instances) == 0:
        return instances
    centers = (instances.pred_boxes.tensor[:, 0] + instances.pred_boxes.tensor[:, 2]) / 2.0
    order = torch.argsort(centers)
    return instances[order]

def init_slots():
    # 100, 10, 1의 자리용 슬롯 3개
    return [
        {"char": None, "score": 0.0, "x": None, "y": None},
        {"char": None, "score": 0.0, "x": None, "y": None},
        {"char": None, "score": 0.0, "x": None, "y": None},
    ]

def update_slots_with_instances(slots, instances, metadata):
    """
    현재 프레임의 숫자 Instances 를 왼쪽→오른쪽 정렬해서
    최대 3개까지 슬롯(100,10,1 자리)에 매칭시키고,
    각 슬롯 내에서 score 가 더 높은 숫자로 교체.
    슬롯 위치 자체는 고정된 3개이며, 자리 재배치는 하지 않는다.
    """
    if len(instances) == 0:
        return

    inst_sorted = sort_by_x(instances)
    boxes = inst_sorted.pred_boxes.tensor.numpy()
    scores = inst_sorted.scores.cpu().numpy()

    # y 차이는 같은 라인 여부 판별용
    ys = (boxes[:, 1] + boxes[:, 3]) * 0.5
    heights = boxes[:, 3] - boxes[:, 1]
    avg_h = heights.mean() if len(heights) > 0 else 1.0
    y_tol = avg_h * 0.5  # y 축 허용 오차 (픽셀 단위)

    for idx in range(min(3, len(inst_sorted))):
        cls_id = int(inst_sorted.pred_classes[idx])
        ch = decode_label_char(cls_id, metadata)
        score = float(scores[idx])
        x1, y1, x2, y2 = boxes[idx]
        xc = 0.5 * (x1 + x2)
        yc = 0.5 * (y1 + y2)

        slot = slots[idx]  # 왼→오 순으로 slot 0,1,2 사용

        # y 위치가 기존 슬롯과 너무 다르면 다른 줄일 가능성이 높음
        if slot["char"] is not None and slot["y"] is not None:
            if abs(yc - slot["y"]) > y_tol:
                # 같은 슬롯으로 보기 어렵다 → 건너뜀
                continue

        # score 가 더 좋을 때만 갱신
        if score >= slot["score"]:
            slot["char"]  = ch
            slot["score"] = score
            slot["x"]     = xc
            slot["y"]     = yc

def build_final_code_from_slots(slots):
    """
    슬롯 3개가 모두 채워져 있으면 "XYZ", 하나라도 비어있으면 "NONE".
    """
    digits = []
    for s in slots:
        if s["char"] is None:
            return "NONE"
        digits.append(s["char"])
    return "".join(digits)

# ─────────────────────────────────────────────
# 메인 루프 (폴더 이미지 → 영상처럼 처리)
# ─────────────────────────────────────────────
def main():
    predictor, metadata, mark_class_idx = setup_detectron()
    ctx, sock = make_zmq_sender()

    frame_interval = 1.0 / max(1, FPS)
    use_cuda = torch.cuda.is_available()

    image_paths = sorted(
        glob.glob(os.path.join(IMAGE_DIR, "*")),
        key=numeric_sort_key
    )
    image_paths = [p for p in image_paths
                   if os.path.splitext(p)[1].lower() in [".jpg", ".jpeg", ".png", ".bmp"]]

    if not image_paths:
        print(f"[ERROR] No images found in {IMAGE_DIR}")
        return

    print(f"[INFO] IMAGE_DIR: {IMAGE_DIR}, num_images={len(image_paths)}, FPS={FPS}, CUDA={use_cuda}")

    # 상태 관리
    frame_idx = 0
    idx = 0  # 이미지 인덱스 (순환)

    mark_ready = False    # mark 를 본 뒤 숫자를 기다리는 상태인지
    in_wagon  = False     # START 이후 번호 수집 중인지
    no_digit_frames = 0   # in_wagon 중 연속 숫자 미검출 카운트
    slots = init_slots()  # 자리별 최고 숫자 정보

    try:
        while True:
            t0 = time.time()

            img_path = image_paths[idx]
            idx = (idx + 1) % len(image_paths)

            img = cv2.imread(img_path)
            if img is None:
                print(f"[WARN] failed to read image: {img_path}")
                continue

            img = cv2.resize(img, (960, 540))
            img_h, img_w = img.shape[:2]

            run_detect = (frame_idx % DETECT_INTERVAL_FRAMES == 0)
            send_code = ""

            if run_detect:
                with torch.inference_mode():
                    outputs = predictor(img)
                instances = outputs["instances"].to("cpu")

                # mark / 숫자 분리
                mark_present = False
                mark_instances = None

                if len(instances) > 0:
                    if mark_class_idx is not None:
                        mask_mark = (instances.pred_classes == mark_class_idx)
                        if mask_mark.any():
                            mark_present = True
                            mark_idxs = torch.nonzero(mask_mark).squeeze(1)
                            mark_instances = instances[mark_idxs]

                        # 숫자는 mark 가 아닌 것들
                        num_instances = instances[~mask_mark]
                    else:
                        num_instances = instances
                else:
                    num_instances = instances

                # 숫자 영역 필터 (오검 줄이기)
                num_instances = filter_digit_region(num_instances, img_h, img_w)

                # 화면 오버레이: 숫자 박스는 검출될 때마다 모두 그리기
                for i in range(len(num_instances)):
                    x1, y1, x2, y2 = num_instances.pred_boxes.tensor[i].numpy().astype(int)
                    cls_id = int(num_instances.pred_classes[i])
                    ch = decode_label_char(cls_id, metadata)
                    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(img, ch,
                                (x1, max(y1 - 10, 20)),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 2)

                # (선택) mark 도 박스로 보고 싶으면 여기서 그리면 됨
                if mark_instances is not None:
                    for i in range(len(mark_instances)):
                        x1, y1, x2, y2 = mark_instances.pred_boxes.tensor[i].numpy().astype(int)
                        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
                        cv2.putText(img, "M",
                                    (x1, max(y1 - 10, 20)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 2)

                # ── 상태 머신 ──
                # 1) 아직 대차 구간이 아닐 때
                if not in_wagon:
                    # mark 를 처음 보면 mark_ready 플래그 켜기
                    if not mark_ready and mark_present:
                        mark_ready = True

                    # mark 를 본 뒤에 숫자가 나오면 START
                    if mark_ready and len(num_instances) > 0:
                        in_wagon = True
                        slots = init_slots()
                        no_digit_frames = 0
                        send_code = "START"
                        print("[WAGON] START")

                    # 아직 in_wagon 이 아니면 더 할 건 없음

                # 2) 대차 번호 수집 중(in_wagon=True)
                if in_wagon:
                    if len(num_instances) == 0:
                        no_digit_frames += 1
                    else:
                        no_digit_frames = 0
                        # 현재 프레임의 숫자들로 슬롯 업데이트
                        update_slots_with_instances(slots, num_instances, metadata)

                    # 연속 NO_DIGIT_END_FRAMES 만큼 숫자가 안 나오면 END
                    if no_digit_frames >= NO_DIGIT_END_FRAMES:
                        final_code = build_final_code_from_slots(slots)
                        send_code = final_code
                        print(f"[WAGON] END → {final_code}")

                        # 상태 초기화
                        in_wagon = False
                        mark_ready = False
                        slots = init_slots()
                        no_digit_frames = 0

                # 메모리 정리
                del outputs, instances, num_instances

            # ── JPEG 인코딩 & 송신 ──
            ok, jpg_buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
            if not ok:
                continue

            if send_code or EMPTY_CODE_OK:
                code_bytes = send_code.encode("utf-8") if send_code else b""
                sock.send_multipart([code_bytes, jpg_buf.tobytes()])
                if send_code:
                    print(f"[SEND] code='{send_code}'")

            # FPS 제어
            elapsed = time.time() - t0
            remain = frame_interval - elapsed
            if remain > 0:
                time.sleep(remain)

            frame_idx += 1

    except KeyboardInterrupt:
        pass

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
