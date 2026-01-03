# linux/main_run.py
# --------------------------------------------------
# 단일 파일 통합본 (State Machine 제거 버전)
# - 상태 판단 로직은 CarEventBus로 위임
# - digit_utils 함수들은 하단에 포함됨
# --------------------------------------------------

import time
import cv2
import torch

from detectron2.config import get_cfg
from detectron2.engine import DefaultPredictor
from detectron2.data import MetadataCatalog
from detectron2.projects import point_rend

from config import config
from utils.zmq_utils import ZmqSendWorker
from utils.shared_mem_utils import open_or_create_shm

# [수정] 외부 모듈 import 제거하고 파일 하단에 정의된 함수 사용
# from utils.digit_utils import has_any_digit, build_code_best3 ... (제거됨)

from core.car_event_bus import CarEventBus
from core.wheel_flag_watcher import WheelFlagWatcher


# ==================================================
# Detectron2 setup
# ==================================================
def setup_detectron():
    cfg = get_cfg()
    point_rend.add_pointrend_config(cfg)
    cfg.merge_from_file(config.CFG_PATH)
    cfg.MODEL.WEIGHTS = config.WEIGHTS_PATH
    cfg.INPUT.MIN_SIZE_TEST = config.D2_MIN_SIZE_TEST
    cfg.INPUT.MAX_SIZE_TEST = config.D2_MAX_SIZE_TEST
    cfg.MODEL.ROI_HEADS.NUM_CLASSES = config.D2_NUM_CLASSES
    cfg.MODEL.POINT_HEAD.NUM_CLASSES = config.D2_NUM_CLASSES
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = config.D2_SCORE_THRESH_TEST
    cfg.MODEL.DEVICE = config.get_device()

    metadata = None
    mark_class_idx = None
    try:
        ckpt = torch.load(config.WEIGHTS_PATH, map_location="cpu")
        meta_name = config.D2_META_NAME
        if isinstance(ckpt, dict) and ("metadata" in ckpt):
            MetadataCatalog.get(meta_name).set(**ckpt["metadata"])
        metadata = MetadataCatalog.get(meta_name)

        if metadata is not None and hasattr(metadata, "thing_classes"):
            for idx, name in enumerate(metadata.thing_classes):
                if str(name).lower() == str(config.D2_MARK_CLASS_NAME).lower():
                    mark_class_idx = idx
                    print("[META] mark class idx =", mark_class_idx)
                    break
    except Exception as e:
        print("[WARN] metadata load failed:", e)

    predictor = DefaultPredictor(cfg)
    return predictor, metadata, mark_class_idx

# ==================================================
# Helpers
# ==================================================
def _resize_keep_aspect(img, max_w):
    if img is None or int(max_w) <= 0: return img, 1.0
    h, w = img.shape[:2]
    if w <= int(max_w): return img, 1.0
    scale = float(max_w) / float(w)
    return cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA), scale

def _draw_digit_boxes(img, instances, metadata, score_thresh=0.0):
    if img is None or instances is None: return img
    try:
        inst = instances.to("cpu")
        boxes = inst.pred_boxes.tensor.numpy()
        scores = inst.scores.numpy()
        classes = inst.pred_classes.numpy()
    except: return img
    
    for i in range(len(scores)):
        if scores[i] < score_thresh: continue
        cls_id = int(classes[i])
        ch = decode_label_char(classes[i], metadata)
        if not _is_digit_char(ch): continue
        x1, y1, x2, y2 = map(int, boxes[i][:4])
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(img, f"{ch}:{scores[i]:.2f}", (x1, max(y1-5, 0)), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    return img

# ==================================================
# Car number mode (수정됨)
# ==================================================
def run_car_number_mode(predictor, metadata, mark_class_idx, car_bus, shm_array, score_thresh=0.0):
    cap = cv2.VideoCapture(config.RTSP_URL)
    if not cap.isOpened():
        print("[CAR] cannot open:", config.RTSP_URL)
        return

    frame_interval = 1.0 / float(config.FPS) if float(getattr(config, "FPS", 0.0)) > 0 else 0.0
    show_win = bool(getattr(config, "SHOW_DEBUG_WINDOW", False))

    print("[MAIN] Start Loop (State Machine managed by CarEventBus)")

    while True:
        t0 = time.time()
        ret, img0 = cap.read()
        if not ret or img0 is None:
            cap.release()
            time.sleep(float(config.RECONNECT_WAIT_SEC))
            cap = cv2.VideoCapture(config.RTSP_URL)
            continue

        # 1) 추론
        infer_img, infer_scale = _resize_keep_aspect(img0, int(getattr(config, "INFER_MAX_WIDTH", 0)))
        outputs = predictor(infer_img)

        instances = None
        if "instances" in outputs:
            instances = outputs["instances"].to("cpu")

        # 2) 데이터 추출 (판단 로직 제거, 단순히 유틸 함수 호출)
        has_digit = has_any_digit(instances, metadata, score_thresh)
        current_frame_code = build_code_best3(instances, metadata, score_thresh)

        # 3) [핵심] Bus에게 상태 업데이트 위임
        #    Main은 "지금 숫자가 있다/없다", "보이는 번호는 이거다" 라고만 전달
        if car_bus is not None:
            car_bus.update_wagon_status(has_digit, current_frame_code, shm_array)

        # 4) 디버그 표시
        if show_win:
            dbg = infer_img.copy()
            if bool(getattr(config, "DRAW_DIGIT_BOX", True)):
                dbg = _draw_digit_boxes(dbg, instances, metadata, score_thresh)
            
            # 현재 상태 표시 (Bus 내부 변수 참조)
            state_txt = "WAGON: ON" if car_bus and car_bus.in_wagon else "WAGON: OFF"
            best_txt = car_bus.session_best_code if car_bus else "FFF"
            
            cv2.putText(dbg, state_txt, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,0,255), 2)
            cv2.putText(dbg, f"CODE: {best_txt}", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,255,0), 2)

            cv2.imshow("CAR_NUMBER_DEBUG", dbg)
            if (cv2.waitKey(1) & 0xFF) == 27:
                break

        # FPS 제어
        elapsed = time.time() - t0
        if frame_interval > 0:
            time.sleep(max(0, frame_interval - elapsed))
        else:
            time.sleep(0.001)

    cap.release()
    cv2.destroyAllWindows()

# ==================================================
# main
# ==================================================
def main():
    shm = None
    shm_array = None
    zmq_sender = None
    ws_watcher = None
    ds_watcher = None

    try:
        predictor, metadata, mark_class_idx = setup_detectron()
        print("[MAIN] Detectron2 ready.")

        zmq_sender = ZmqSendWorker(bind_addr=config.PUSH_BIND, debug_print=False)
        zmq_sender.start()

        shm, shm_array = open_or_create_shm(config.SHM_NAME, config.SHM_SIZE)
        
        # CarEventBus 생성 (State Machine 포함됨)
        car_bus = CarEventBus(zmq_sender, debug_print=False)

        ws_watcher = WheelFlagWatcher("WS", shm_array, car_bus,
                                      poll_interval=config.WHEEL_POLL_INTERVAL_SEC,
                                      clear_flag_on_read=True, debug_print=False)
        ds_watcher = WheelFlagWatcher("DS", shm_array, car_bus,
                                      poll_interval=config.WHEEL_POLL_INTERVAL_SEC,
                                      clear_flag_on_read=True, debug_print=False)
        ws_watcher.start()
        ds_watcher.start()

        run_car_number_mode(
            predictor=predictor,
            metadata=metadata,
            mark_class_idx=mark_class_idx,
            car_bus=car_bus,
            shm_array=shm_array,
            score_thresh=0.0,
        )

    except KeyboardInterrupt:
        print("[MAIN] Exit")
    except Exception as e:
        print("[MAIN] error:", e)
    finally:
        if ws_watcher: ws_watcher.stop()
        if ds_watcher: ds_watcher.stop()
        if zmq_sender: zmq_sender.stop()
        if shm: shm.close()

# ==================================================
# digit_utils.py 통합본 (기존 코드 유지)
# ==================================================
def _is_digit_char(ch):
    if ch is None or len(ch) != 1: return False
    return "0" <= ch <= "9"

def decode_label_char(cls_id, metadata):
    label = ""
    if metadata and hasattr(metadata, "thing_classes"):
        try:
            idx = int(cls_id)
            if 0 <= idx < len(metadata.thing_classes):
                label = str(metadata.thing_classes[idx])
        except: label = ""
    if label == "":
        try: label = str(int(cls_id))
        except: label = ""
    if label == "": return ""
    return label[-1]

def extract_digit_detections(instances, metadata, score_thresh=0.0):
    out = []
    if instances is None: return out
    try:
        inst = instances.to("cpu")
    except: inst = instances
    try:
        boxes = inst.pred_boxes.tensor.numpy()
        scores = inst.scores.numpy()
        classes = inst.pred_classes.numpy()
    except: return out

    n = len(scores)
    i = 0
    while i < n:
        sc = float(scores[i])
        if sc < float(score_thresh):
            i += 1; continue
        cls_id = int(classes[i])
        ch = decode_label_char(cls_id, metadata)
        if not _is_digit_char(ch):
            i += 1; continue

        x1, y1, x2, y2 = map(float, boxes[i][:4])
        cx, cy = (x1+x2)/2.0, (y1+y2)/2.0
        out.append({"x": cx, "y": cy, "score": sc, "ch": ch})
        i += 1
    return out

def has_any_digit(instances, metadata, score_thresh=0.0):
    return len(extract_digit_detections(instances, metadata, score_thresh)) > 0

def _sort_by_x_inplace(items):
    n = len(items)
    i = 0
    while i < n:
        j = 0
        while j + 1 < n:
            if float(items[j]["x"]) > float(items[j + 1]["x"]):
                tmp = items[j]
                items[j] = items[j + 1]
                items[j + 1] = tmp
            j += 1
        i += 1

def build_code_best3(instances, metadata, score_thresh=0.0):
    digits = extract_digit_detections(instances, metadata, score_thresh)
    if len(digits) < 3: return "FFF"

    best_triplet = None
    best_y_spread = None
    best_score_sum = None

    a = 0
    while a < len(digits) - 2:
        b = a + 1
        while b < len(digits) - 1:
            c = b + 1
            while c < len(digits):
                d1, d2, d3 = digits[a], digits[b], digits[c]
                ys = [float(d1["y"]), float(d2["y"]), float(d3["y"])]
                y_spread = max(ys) - min(ys)
                score_sum = float(d1["score"]) + float(d2["score"]) + float(d3["score"])

                ok = False
                if best_triplet is None: ok = True
                else:
                    if y_spread < best_y_spread: ok = True
                    elif y_spread == best_y_spread and score_sum > best_score_sum: ok = True

                if ok:
                    best_triplet = [d1, d2, d3]
                    best_y_spread = y_spread
                    best_score_sum = score_sum
                c += 1
            b += 1
        a += 1

    if best_triplet is None: return "FFF"
    _sort_by_x_inplace(best_triplet)
    return best_triplet[0]["ch"] + best_triplet[1]["ch"] + best_triplet[2]["ch"]


if __name__ == "__main__":
    main()