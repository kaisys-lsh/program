# linux/main_run.py
# --------------------------------------------------
# 단일 파일 통합본 (비동기 영상 처리 + 속도 제어 적용)
# - URL_worker: time.sleep(0.03) 추가로 재생 속도 동기화
# --------------------------------------------------

import time
import cv2
import torch
import struct
import numpy as np
from multiprocessing import Process, Event, shared_memory

from detectron2.config import get_cfg
from detectron2.engine import DefaultPredictor
from detectron2.data import MetadataCatalog
from detectron2.projects import point_rend

from config import config
from utils.zmq_utils import ZmqSendWorker
from utils.shared_mem_utils import open_or_create_shm

from core.car_event_bus import CarEventBus
from core.wheel_flag_watcher import WheelFlagWatcher


# ==================================================
# [설정] 영상 공유 메모리 설정
# ==================================================
IMG_SHM_NAME = "shm_rtsp_frame_buffer"
IMG_SHM_SIZE = 1920 * 1080 * 3 + 4096


# ==================================================
# [Process] URL_worker (영상 수집 전담)
# ==================================================
def URL_worker(stop_event, rtsp_url, shm_name, shm_size):
    """
    RTSP/파일 영상을 읽어서 공유 메모리에 올리는 프로세스.
    CheckWheelStatus.py와 동일하게 0.03초 딜레이를 주어 속도를 제어함.
    """
    print(f"[URL_worker] 영상 읽기 시작: {rtsp_url}")
    
    try:
        shm = shared_memory.SharedMemory(name=shm_name, create=False)
    except FileNotFoundError:
        shm = shared_memory.SharedMemory(name=shm_name, create=True, size=shm_size)

    shm.buf[0] = 0  # 연결 상태
    shm.buf[1] = 0  # 데이터 플래그

    cap = cv2.VideoCapture(rtsp_url)
    
    # 내부 버퍼 최소화
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    reconnect_delay = 2.0
    fail_count = 0

    while not stop_event.is_set():
        if not cap.isOpened():
            shm.buf[0] = 0
            time.sleep(reconnect_delay)
            cap.open(rtsp_url)
            continue

        ret, frame = cap.read()
        if not ret:
            fail_count += 1
            if fail_count > 30:
                print("[URL_worker] Read Failed. Reconnecting...")
                cap.release()
                fail_count = 0
                shm.buf[0] = 0
                time.sleep(reconnect_delay)
            else:
                time.sleep(0.01)
            continue
        
        fail_count = 0
        shm.buf[0] = 1 # 연결 OK

        # Main 프로세스가 이전 데이터를 가져갔을 때만(buf[1]==0) 씀
        if shm.buf[1] == 0:
            try:
                h, w, c = frame.shape
                if not frame.flags['C_CONTIGUOUS']:
                    frame = np.ascontiguousarray(frame)

                frame_bytes = frame.tobytes()
                
                header = struct.pack('HHB', w, h, c)
                total_len = len(header) + len(frame_bytes)
                
                if 2 + total_len <= shm_size:
                    shm.buf[2 : 2+len(header)] = header
                    shm.buf[2+len(header) : 2+total_len] = frame_bytes
                    shm.buf[1] = 1 
            except Exception as e:
                print(f"[URL_worker] SHM Write Error: {e}")
                shm.buf[1] = 0
        
        # ★ [수정됨] CheckWheelStatus.py와 동일하게 속도 조절 (약 33 FPS)
        # 이 부분이 없으면 파일 읽기 시 배속 재생(스킵) 현상이 발생함
        time.sleep(0.03)

    cap.release()
    shm.close()
    print("[URL_worker] 프로세스 종료")


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
# Consumer Loop
# ==================================================
def run_car_number_loop(predictor, metadata, mark_class_idx, car_bus, shm_array, img_shm, stop_event, score_thresh=0.0):
    show_win = bool(getattr(config, "SHOW_DEBUG_WINDOW", False))
    infer_width = int(getattr(config, "INFER_MAX_WIDTH", 0))

    print("[MAIN] 추론 루프 시작 (Shared Memory)")

    try:
        while not stop_event.is_set():
            # 1. 카메라 연결 대기
            if img_shm.buf[0] == 0:
                time.sleep(0.1)
                continue

            # 2. 새 데이터 확인
            if img_shm.buf[1] == 1:
                # 데이터 읽기
                header_bytes = bytes(img_shm.buf[2:7])
                w, h, c = struct.unpack('HHB', header_bytes)
                data_len = w * h * c
                
                raw_data = np.frombuffer(img_shm.buf[7 : 7+data_len], dtype=np.uint8)
                img0 = raw_data.reshape((h, w, c)).copy()
                
                # ★ 읽었으니 즉시 플래그 내림 (Producer가 다음 프레임 준비하도록)
                img_shm.buf[1] = 0
                
                # -----------------------------------------------------------
                # [추론 및 로직]
                # -----------------------------------------------------------
                infer_img, infer_scale = _resize_keep_aspect(img0, infer_width)
                outputs = predictor(infer_img)

                instances = None
                if "instances" in outputs:
                    instances = outputs["instances"].to("cpu")

                has_digit = has_any_digit(instances, metadata, score_thresh)
                current_frame_code = build_code_best3(instances, metadata, score_thresh)

                if car_bus is not None:
                    car_bus.update_wagon_status(has_digit, current_frame_code, shm_array)

                # 디버그 표시
                if show_win:
                    dbg = infer_img.copy()
                    if bool(getattr(config, "DRAW_DIGIT_BOX", True)):
                        dbg = _draw_digit_boxes(dbg, instances, metadata, score_thresh)
                    
                    state_txt = "WAGON: ON" if car_bus and car_bus.in_wagon else "WAGON: OFF"
                    best_txt = car_bus.session_best_code if car_bus else "FFF"
                    
                    cv2.putText(dbg, state_txt, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,0,255), 2)
                    cv2.putText(dbg, f"CODE: {best_txt}", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,255,0), 2)

                    cv2.imshow("CAR_NUMBER_DEBUG", dbg)
                    # 여기서 waitKey는 화면 갱신용으로 최소한만 사용 (흐름 제어는 URL_worker가 담당)
                    if (cv2.waitKey(1) & 0xFF) == 27:
                        stop_event.set()
                        break
            else:
                # 데이터가 아직 없으면 아주 짧게 대기
                time.sleep(0.001)

    except KeyboardInterrupt:
        print("[MAIN] Loop Interrupted")
    finally:
        cv2.destroyAllWindows()


# ==================================================
# main
# ==================================================
def main():
    stop_event = Event()
    img_shm = None
    p_cam = None

    # 로직 관련 객체들
    shm = None
    shm_array = None
    zmq_sender = None
    ws_watcher = None
    ds_watcher = None

    try:
        # 1. 영상 공유 메모리 생성
        try:
            tmp = shared_memory.SharedMemory(name=IMG_SHM_NAME, create=False)
            tmp.close()
            tmp.unlink()
        except:
            pass

        img_shm = shared_memory.SharedMemory(name=IMG_SHM_NAME, create=True, size=IMG_SHM_SIZE)
        img_shm.buf[0] = 0
        img_shm.buf[1] = 0

        # 2. URL_worker 프로세스 시작
        p_cam = Process(target=URL_worker, 
                        args=(stop_event, config.RTSP_URL, IMG_SHM_NAME, IMG_SHM_SIZE), 
                        name="URL_worker_Process")
        p_cam.start()

        # 3. AI 모델 로드
        predictor, metadata, mark_class_idx = setup_detectron()
        print("[MAIN] Detectron2 ready.")

        # 4. 통신 및 로직 모듈 초기화
        zmq_sender = ZmqSendWorker(bind_addr=config.PUSH_BIND, debug_print=False)
        zmq_sender.start()

        shm, shm_array = open_or_create_shm(config.SHM_NAME, config.SHM_SIZE)
        
        car_bus = CarEventBus(zmq_sender, debug_print=False)

        ws_watcher = WheelFlagWatcher("WS", shm_array, car_bus,
                                      poll_interval=config.WHEEL_POLL_INTERVAL_SEC,
                                      clear_flag_on_read=True, debug_print=False)
        ds_watcher = WheelFlagWatcher("DS", shm_array, car_bus,
                                      poll_interval=config.WHEEL_POLL_INTERVAL_SEC,
                                      clear_flag_on_read=True, debug_print=False)
        ws_watcher.start()
        ds_watcher.start()

        # 5. 추론 루프 진입
        run_car_number_loop(
            predictor=predictor,
            metadata=metadata,
            mark_class_idx=mark_class_idx,
            car_bus=car_bus,
            shm_array=shm_array,
            img_shm=img_shm,
            stop_event=stop_event,
            score_thresh=0.0,
        )

    except KeyboardInterrupt:
        print("[MAIN] Exit")
    except Exception as e:
        print("[MAIN] error:", e)
    finally:
        stop_event.set()
        
        if p_cam:
            p_cam.join()
        
        if ws_watcher: ws_watcher.stop()
        if ds_watcher: ds_watcher.stop()
        if zmq_sender: zmq_sender.stop()
        
        if img_shm:
            img_shm.close()
            try:
                img_shm.unlink()
            except: pass

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