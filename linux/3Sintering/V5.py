# sender_rtsp_push.py
import os, time, cv2, zmq, torch, gc
import numpy as np
from datetime import datetime

from detectron2.config import get_cfg
from detectron2.engine import DefaultPredictor
from detectron2.data import MetadataCatalog
from detectron2.projects import point_rend
from detectron2.structures import Instances, Boxes

# ─────────────────────────────────────────────
# [환경설정]
# ─────────────────────────────────────────────
RTSP_URL      = "http://127.0.0.1:8000/video"  # ← 카메라 URL로 변경
FPS           = 15                             # 전송 FPS (지연/부하 조절)
JPEG_QUALITY  = 80

CFG_PATH      = "/home/kaisys/detectron2/projects/PointRend/configs/InstanceSegmentation/pointrend_rcnn_R_50_FPN_3x_coco.yaml"
WEIGHTS_PATH  = "/home/kaisys/Project_SH/test3/번호인식_V4.pth"

PUSH_BIND     = "tcp://*:5577"    # PUSH bind 주소
EMPTY_CODE_OK = True              # 검출 실패시 빈 문자열도 전송할지 여부

# RTSP 옵션
RECONNECT_WAIT_SEC = 2.0          # 끊겼을 때 재연결 대기
USE_FFMPEG         = True         # OpenCV FFMPEG 백엔드 사용
DROP_OLD_FRAMES    = True         # 내부 버퍼를 최소화하여 최신 프레임 위주

# 대차 수집 윈도우 (초)
WAGON_WINDOW_SEC   = 3.0          # 마크/번호 첫 검출 이후 5초를 하나의 대차로 간주

# ─────────────────────────────────────────────
# [01] 숫자 박스 정렬/선택/문자 추출
# ─────────────────────────────────────────────
def sort_number(instances):
    """x중심 기준으로 왼쪽→오른쪽 정렬"""
    if len(instances) == 0:
        return instances
    centers = (instances.pred_boxes.tensor[:, 0] + instances.pred_boxes.tensor[:, 2]) / 2
    return instances[torch.argsort(centers)]

def pick_best(inst, y_tol=20):
    """
    여러 숫자 박스 중에서
    - y가 비슷하고
    - x-span이 가장 좁고
    - score 합이 큰
    3개를 골라서 반환
    """
    n = len(inst)
    if n < 3:
        return None
    boxes, scores = inst.pred_boxes.tensor, inst.scores
    cx = (boxes[:, 0] + boxes[:, 2]) / 2
    cy = (boxes[:, 1] + boxes[:, 3]) / 2
    best, best_span, best_conf = None, float("inf"), -float("inf")
    for trio in torch.combinations(torch.arange(n), r=3):
        if (cy[trio].max() - cy[trio].min()) > y_tol:
            continue
        span = cx[trio].max() - cx[trio].min()
        conf = scores[trio].sum()
        if span < best_span or (span == best_span and conf > best_conf):
            best, best_span, best_conf = trio, span, conf
    return inst[best] if best is not None else None

def decode_three_digits(inst, metadata):
    """
    Instances에서 3자리 번호를 추출.
    - Y축 비슷한 3개 선별 (pick_best)
    - x정렬
    """
    inst3 = pick_best(inst)
    if inst3 is None or len(inst3) != 3:
        return "", None
    inst3 = sort_number(inst3)

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

    return "".join(chars), inst3

def mark_and_code(img, inst, metadata):
    """
    화면에 숫자 박스를 그려주는 용도.
    - 번호(마크 제외된 inst)를 넣어줘야 함.
    - 3자리 완성된 경우에만 오버레이 그리기.
    """
    code, inst3 = decode_three_digits(inst, metadata)
    if not code or inst3 is None:
        return ""

    for i in range(len(inst3)):
        x1, y1, x2, y2 = inst3.pred_boxes.tensor[i].cpu().numpy().astype(int)
        cls_id = int(inst3.pred_classes[i])

        label = ""
        if metadata is not None and hasattr(metadata, "thing_classes"):
            if 0 <= cls_id < len(metadata.thing_classes):
                label = metadata.thing_classes[cls_id]
        if not label:
            label = str(cls_id)
        ch = (label[-1] if label else "0")[0]

        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(img, ch, (x1, max(y1 - 10, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    return code

# ─────────────────────────────────────────────
# [02] Detectron2 설정 (마크 클래스 인덱스 포함)
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
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = 0.7
    cfg.MODEL.DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

    metadata = None
    mark_class_idx = None
    try:
        ckpt = torch.load(WEIGHTS_PATH, map_location="cpu")
        meta_name = "inference_meta_pointrend_numbers"
        MetadataCatalog.get(meta_name).set(**ckpt.get("metadata", {}))
        metadata = MetadataCatalog.get(meta_name)

        # thing_classes 안에서 "mark" 클래스 인덱스 찾기
        if metadata is not None and hasattr(metadata, "thing_classes"):
            for i, name in enumerate(metadata.thing_classes):
                if str(name).lower() == "mark":
                    mark_class_idx = i
                    print(f"[META] 'mark' class index = {mark_class_idx}")
                    break
            if mark_class_idx is None:
                print("[WARN] 'mark' 클래스 이름을 thing_classes에서 찾지 못했습니다.")
    except Exception as e:
        print("[WARN] 메타데이터 로드 실패:", e)
        metadata = None
        mark_class_idx = None

    predictor = DefaultPredictor(cfg)
    return predictor, metadata, mark_class_idx

# ─────────────────────────────────────────────
# [03] ZMQ 송신 (PUSH, 최신 우선)
# ─────────────────────────────────────────────
def make_zmq_sender():
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.PUSH)
    sock.setsockopt(zmq.SNDHWM, 1)  # 최신 프레임 위주
    sock.bind(PUSH_BIND)
    print(f"[PUSH] bind {PUSH_BIND}, warmup 0.5s…")
    time.sleep(0.5)
    return ctx, sock

# ─────────────────────────────────────────────
# [04] RTSP 캡처 열기/재연결
# ─────────────────────────────────────────────
def open_capture(url):
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG if USE_FFMPEG else 0)
    if DROP_OLD_FRAMES:
        # 일부 백엔드는 무시될 수 있지만, 가능하면 버퍼 최소화
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
    if not cap.isOpened():
        return None
    # 버퍼에 쌓인 초기 프레임 몇 개 버려서 지연감소
    for _ in range(3):
        cap.read()
    return cap

# ─────────────────────────────────────────────
# [05] 메인 루프 (RTSP 입력 → 추론 → [code, jpeg] 전송)
# ─────────────────────────────────────────────
def main():
    predictor, metadata, mark_class_idx = setup_detectron()
    ctx, sock = make_zmq_sender()

    frame_interval = 1.0 / max(1, FPS)
    frame_count = 0
    use_cuda = torch.cuda.is_available()

    cap = None
    print(f"[INFO] RTSP input: {RTSP_URL}, FPS={FPS}, CUDA={use_cuda}")

    # ── 대차 상태 관리 변수 ─────────────────────
    in_wagon = False             # 현재 5초 수집 윈도우 안인지
    wagon_start_ts = None        # 이 대차 수집 시작 시각
    collected_boxes = []         # 번호 박스들 (마크 제외) [x1, y1, x2, y2]
    collected_classes = []       # 번호 클래스 ID
    collected_scores = []        # 번호 score
    last_image_size = (720, 1280)

    have_mark_class = (mark_class_idx is not None)

    try:
        while True:
            # (재)연결
            if cap is None or not cap.isOpened():
                print("[RTSP] connecting...")
                cap = open_capture(RTSP_URL)
                if cap is None:
                    print(f"[RTSP] open failed. retry in {RECONNECT_WAIT_SEC}s")
                    time.sleep(RECONNECT_WAIT_SEC)
                    continue
                print("[RTSP] connected.")

            t0 = time.time()

            # 최신 프레임 위주로 드랍 읽기 (옵션)
            ret, img = cap.read()
            if not ret or img is None:
                print("[RTSP] read failed. reconnect...")
                cap.release()
                cap = None
                time.sleep(RECONNECT_WAIT_SEC)
                continue

            now = time.time()

            # 추론
            with torch.inference_mode():
                outputs = predictor(img)
            instances = outputs["instances"].to("cpu")

            # mark 존재 여부
            mark_present = False
            if have_mark_class and len(instances) > 0:
                try:
                    mark_present = (instances.pred_classes == mark_class_idx).any().item()
                except Exception:
                    mark_present = False

            # 번호만 필터링 (마크 제외)
            if len(instances) > 0:
                if have_mark_class:
                    num_mask = (instances.pred_classes != mark_class_idx)
                    num_instances = instances[num_mask]
                else:
                    num_mask = torch.ones(len(instances), dtype=torch.bool)
                    num_instances = instances
            else:
                num_instances = instances  # 빈 Instances

            # ---- 화면 시각화 ----

            # 1) 번호(숫자) 박스 표시 (3자리 완성 시 오버레이)
            if len(num_instances) > 0:
                _ = mark_and_code(img, num_instances, metadata)

            # 2) 마크 박스 표시 (데이터에는 사용 X)
            if have_mark_class and len(instances) > 0:
                mark_mask = (instances.pred_classes == mark_class_idx)
                mark_instances = instances[mark_mask]

                for i in range(len(mark_instances)):
                    x1, y1, x2, y2 = mark_instances.pred_boxes.tensor[i].cpu().numpy().astype(int)
                    cv2.rectangle(img, (x1, y1), (x2, y2), (255, 0, 0), 2)   # 파란색 박스
                    cv2.putText(img, "MARK", (x1, max(y1 - 10, 20)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)

            # 이번 프레임에서 "무언가 검출" 여부 (마크 or 번호)
            has_any_detection = mark_present or (len(num_instances) > 0)

            # ── 대차 상태 머신 (검출 발생 시 5초 수집) ──────────────────
            send_code = ""  # 이 프레임에서 보낼 코드 (대부분 "")

            if not in_wagon:
                # 아직 대차 수집 중이 아님 → 새로 시작할지 판단
                if has_any_detection:
                    # 새 대차 시작
                    in_wagon = True
                    wagon_start_ts = now
                    collected_boxes = []
                    collected_classes = []
                    collected_scores = []
                    h, w = img.shape[:2]
                    last_image_size = (h, w)

                    # 번호가 있다면 저장 (마크는 저장 X)
                    if len(num_instances) > 0:
                        collected_boxes.extend(num_instances.pred_boxes.tensor.numpy().tolist())
                        collected_classes.extend([int(c) for c in num_instances.pred_classes.tolist()])
                        collected_scores.extend(num_instances.scores.tolist())

                    print("[WAGON] 새 대차 시작 (검출 발생, 5초 수집)")

                    # ★ 여기서 "검출이 처음 잡힌 순간" 신호 전송
                    #   윈도우는 START 받으면 1초 뒤에 프레임 저장 등 처리
                    send_code = "START"

            else:
                # 이미 대차 수집 중
                h, w = img.shape[:2]
                last_image_size = (h, w)

                # 번호 있으면 계속 수집
                if len(num_instances) > 0:
                    collected_boxes.extend(num_instances.pred_boxes.tensor.numpy().tolist())
                    collected_classes.extend([int(c) for c in num_instances.pred_classes.tolist()])
                    collected_scores.extend(num_instances.scores.tolist())

                # 5초가 지났다면 이 대차 종료로 판단
                if wagon_start_ts is not None and (now - wagon_start_ts) >= WAGON_WINDOW_SEC:
                    # 수집된 번호들을 가지고 3자리 시도
                    if len(collected_boxes) >= 3:
                        inst_all = Instances(last_image_size)
                        inst_all.pred_boxes = Boxes(torch.tensor(collected_boxes, dtype=torch.float32))
                        inst_all.pred_classes = torch.tensor(collected_classes, dtype=torch.int64)
                        inst_all.scores = torch.tensor(collected_scores, dtype=torch.float32)

                        code3, _ = decode_three_digits(inst_all, metadata)
                        if code3 and len(code3) == 3:
                            final_code = code3           # 정상 3자리 번호
                        else:
                            final_code = "NONE"          # 불량 (번호 불완전)
                    else:
                        final_code = "NONE"              # 번호가 3개 미만 → 무조건 불량

                    send_code = final_code
                    print(f"[WAGON] 대차 종료 → code='{final_code}' (수집 박스 {len(collected_boxes)})")

                    # 상태 초기화
                    in_wagon = False
                    wagon_start_ts = None
                    collected_boxes = []
                    collected_classes = []
                    collected_scores = []

            # JPEG 인코딩
            ok_jpg, jpg_buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
            if not ok_jpg:
                print("[WARN] JPEG 인코딩 실패")
                del outputs, instances, num_instances
                time.sleep(frame_interval)
                continue

            # 전송: [코드, JPEG]
            # - 대부분 프레임: send_code == "" (영상만)
            # - 대차 시작 프레임: send_code == "START"
            # - 5초 수집 후 대차 종료 프레임: send_code == "123" 또는 "NONE"
            if send_code or EMPTY_CODE_OK:
                code_bytes = send_code.encode("utf-8") if send_code else b""
                sock.send_multipart([code_bytes, jpg_buf.tobytes()])
                if send_code:
                    print(f"[SEND] code='{send_code}' jpg={len(jpg_buf)}")
                else:
                    # 필요하면 여기서 프레임 전송 로그
                    pass

            # ── 메모리/리소스 관리 ──
            frame_count += 1
            del outputs, instances, num_instances, jpg_buf
            if frame_count % 120 == 0:
                if use_cuda:
                    torch.cuda.empty_cache()
                gc.collect()

            # FPS 유지
            elapsed = time.time() - t0
            remain = frame_interval - elapsed
            if remain > 0:
                time.sleep(remain)

    except KeyboardInterrupt:
        pass
    finally:
        try:
            if cap is not None:
                cap.release()
        except Exception:
            pass
        try:
            sock.close(0)
        except Exception:
            pass
        try:
            ctx.term()
        except Exception:
            pass

if __name__ == "__main__":
    main()
