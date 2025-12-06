# sender_folder_push_vote.py
import os, time, cv2, zmq, torch, gc, glob, re
import numpy as np
from datetime import datetime
from collections import Counter

from detectron2.config import get_cfg
from detectron2.engine import DefaultPredictor
from detectron2.data import MetadataCatalog
from detectron2.projects import point_rend
from detectron2.structures import Instances, Boxes

# ─────────────────────────────────────────────
# [환경설정]
# ─────────────────────────────────────────────
# RTSP 대신 폴더 이미지 사용
IMAGE_DIR     = "/workspace/image"   # ← 여기에 이미지 폴더 경로 넣기
FPS           = 10
JPEG_QUALITY  = 80

CFG_PATH      = "/workspace/detectron2/projects/PointRend/configs/InstanceSegmentation/pointrend_rcnn_R_50_FPN_3x_coco.yaml"
WEIGHTS_PATH  = "/workspace/linux/3Sintering/대차인식WS_V1.pth"

PUSH_BIND     = "tcp://*:5577"  # HMI용 ZMQ 포트 (기존 그대로)

EMPTY_CODE_OK = True
WAGON_WINDOW_SEC   = 3.0

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
# 프레임 단위 숫자 정렬 및 3자리 추출
# ─────────────────────────────────────────────
def sort_number(instances):
    if len(instances) == 0:
        return instances
    centers = (instances.pred_boxes.tensor[:, 0] + instances.pred_boxes.tensor[:, 2]) / 2
    return instances[torch.argsort(centers)]

def try_decode_three_digits(inst, metadata):
    if len(inst) != 3:
        return None

    inst3 = sort_number(inst)

    chars = []
    for i in range(3):
        cls_id = int(inst3.pred_classes[i])

        label = ""
        if metadata is not None and hasattr(metadata, "thing_classes"):
            if 0 <= cls_id < len(metadata.thing_classes):
                label = metadata.thing_classes[cls_id]

        if not label:
            label = str(cls_id)

        ch = (label[-1] if label else "0")[0]
        chars.append(ch)

    return "".join(chars)

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
# 메인 루프 (폴더 이미지 → 영상처럼 처리)
# ─────────────────────────────────────────────
def main():
    predictor, metadata, mark_class_idx = setup_detectron()
    ctx, sock = make_zmq_sender()

    frame_interval = 1.0 / max(1, FPS)
    use_cuda = torch.cuda.is_available()

    # 폴더에서 이미지 목록 읽기 + 정렬
    image_paths = sorted(
        glob.glob(os.path.join(IMAGE_DIR, "*")),
        key=numeric_sort_key
    )
    image_paths = [p for p in image_paths if os.path.splitext(p)[1].lower() in [".jpg", ".jpeg", ".png", ".bmp"]]

    if not image_paths:
        print(f"[ERROR] No images found in {IMAGE_DIR}")
        return

    print(f"[INFO] IMAGE_DIR: {IMAGE_DIR}, num_images={len(image_paths)}, FPS={FPS}, CUDA={use_cuda}")

    # 상태 관리
    in_wagon = False
    wagon_start_ts = None
    frame_candidates = []   # 프레임 단위에서 추출한 3자리 번호들
    idx = 0                 # 이미지 인덱스 (순차 + 반복)

    try:
        while True:
            t0 = time.time()

            img_path = image_paths[idx]
            idx = (idx + 1) % len(image_paths)   # 끝까지 가면 다시 처음으로

            img = cv2.imread(img_path)
            if img is None:
                print(f"[WARN] failed to read image: {img_path}")
                continue

            img = cv2.resize(img, (960, 540))

            # Detectron 추론
            with torch.inference_mode():
                outputs = predictor(img)
            instances = outputs["instances"].to("cpu")

            # mark 여부 판단
            mark_present = False
            if mark_class_idx is not None and len(instances) > 0:
                try:
                    mark_present = (instances.pred_classes == mark_class_idx).any().item()
                except:
                    mark_present = False

            # 번호만 필터
            if len(instances) > 0:
                if mark_class_idx is not None:
                    num_instances = instances[instances.pred_classes != mark_class_idx]
                else:
                    num_instances = instances
            else:
                num_instances = instances

            # 화면 오버레이용 (선택)
            if len(num_instances) == 3:
                code_preview = try_decode_three_digits(num_instances, metadata)
                if code_preview:
                    inst3 = sort_number(num_instances)
                    for i in range(3):
                        x1, y1, x2, y2 = inst3.pred_boxes.tensor[i].numpy().astype(int)
                        cv2.rectangle(img,(x1,y1),(x2,y2),(0,255,0),2)
                        cv2.putText(img, code_preview[i], (x1,max(y1-10,20)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 2.0,(0,255,0),2)

            # ---- START 조건 ----
            has_any_detection = mark_present or (len(num_instances) > 0)

            send_code = ""

            if not in_wagon:
                if has_any_detection:
                    in_wagon = True
                    wagon_start_ts = time.time()
                    frame_candidates = []
                    send_code = "START"
                    print("[WAGON] START")
            else:
                now = time.time()
                # 3초 동안 프레임 단위 번호 저장
                if len(num_instances) == 3:
                    code3 = try_decode_three_digits(num_instances, metadata)
                    if code3:
                        frame_candidates.append(code3)

                # 3초 지났으면 끝
                if now - wagon_start_ts >= WAGON_WINDOW_SEC:
                    if len(frame_candidates) == 0:
                        final_code = "NONE"
                    else:
                        cnt = Counter(frame_candidates)
                        final_code = cnt.most_common(1)[0][0]

                    send_code = final_code
                    print(f"[WAGON] END → {final_code} (frames={len(frame_candidates)})")

                    in_wagon = False
                    wagon_start_ts = None
                    frame_candidates = []

            # JPEG 인코딩
            ok, jpg_buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
            if not ok:
                continue

            # 송신
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

            del outputs, instances, num_instances

    except KeyboardInterrupt:
        pass

    finally:
        try: sock.close()
        except: pass
        try: ctx.term()
        except: pass


if __name__ == "__main__":
    main()
