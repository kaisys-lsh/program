import time
import cv2
import numpy as np
import torch

from detectron2.config import get_cfg
from detectron2.engine import DefaultPredictor
from detectron2.data import MetadataCatalog
from detectron2.projects import point_rend


# ==============================
# 상수(여기서만 조절)
# ==============================
CFG_PATH = r"/home/kaisys/detectron2/projects/PointRend/configs/InstanceSegmentation/pointrend_rcnn_R_50_FPN_3x_coco.yaml"
WEIGHTS_PATH = r"/home/kaisys/Project/대차인식WS_V1.pth"
VIDEO_SRC = r"/home/kaisys/Project/program/output.avi"  # 0 / 파일 / RTSP 가능

TARGET_W = 960
TARGET_H = 540
SHOW_FPS = 1
SCORE_TH = 0.7
WINDOW_NAME = "PointRend Numbers (1~9 only, resized infer+show)"

# --- 프레임 판정 파라미터 ---
PARTIAL_MIN_FRAMES = 2   # 1~2자리: 같은 값이 연속 몇 프레임 이상이면 "유효(오검 아님)"
MISS_FRAMES = 2          # 유효 1~2자리 이후: 몇 프레임 연속 미검출이면 종료(FFF 반환)


def sort_digits(items):
    """검출 결과(list of dict) -> x좌표 기준 정렬된 digit 문자열 리스트"""
    if not items:
        return []

    tmp = []
    for it in items:
        poly = it.get("polygon")
        if poly is None or len(poly) == 0:
            continue
        cx = float(poly[:, 0].mean())
        tmp.append((cx, str(it.get("class_name"))))

    tmp.sort(key=lambda x: x[0])
    return [name for _, name in tmp]


def setup_detectron(cfg_path, weights_path):
    cfg = get_cfg()
    point_rend.add_pointrend_config(cfg)
    cfg.merge_from_file(cfg_path)
    cfg.MODEL.WEIGHTS = weights_path

    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = float(SCORE_TH)
    cfg.MODEL.DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

    meta = None
    allow = []

    try:
        ckpt = torch.load(weights_path, map_location="cpu")
        meta_name = "inference_meta_pointrend_numbers"
        MetadataCatalog.get(meta_name).set(**ckpt.get("metadata", {}))
        meta = MetadataCatalog.get(meta_name)

        if meta is not None and hasattr(meta, "thing_classes"):
            n = int(len(meta.thing_classes))
            cfg.MODEL.ROI_HEADS.NUM_CLASSES = n
            cfg.MODEL.POINT_HEAD.NUM_CLASSES = n

            # ✅ 1~9만 허용 (mark/0 제외)
            i = 0
            while i < len(meta.thing_classes):
                s = str(meta.thing_classes[i]).strip()
                if s in ["0","1", "2", "3", "4", "5", "6", "7", "8", "9"]:
                    allow.append(i)
                i += 1

            print("[META] thing_classes:", list(meta.thing_classes))
            print("[META] allowed idx:", allow)

    except Exception as e:
        print("[WARN] metadata load fail:", e)
        meta = None
        allow = []

    pred = DefaultPredictor(cfg)
    return pred, meta, allow


def resize_img(img, w, h):
    return cv2.resize(img, (int(w), int(h)), interpolation=cv2.INTER_LINEAR)


def infer(pred, img, meta, allow, th):
    """
    img는 이미 리사이즈된 프레임.
    return: (items, vis)
      items: [{"class_name": "1"~"9", "score": float, "polygon": Nx2}, ...]
    """
    out = pred(img)
    inst = out["instances"].to("cpu")

    vis = img.copy()
    items = []

    if len(inst) == 0:
        return items, vis

    cls = inst.pred_classes.numpy()
    scr = inst.scores.numpy()
    msk = inst.pred_masks.numpy()  # bool (N,H,W)

    i = 0
    while i < len(cls):
        c = int(cls[i])
        s = float(scr[i])

        if s < float(th):
            i += 1
            continue

        if allow and (c not in allow):
            i += 1
            continue

        name = str(c)
        if meta is not None and hasattr(meta, "thing_classes"):
            if 0 <= c < len(meta.thing_classes):
                name = str(meta.thing_classes[c])

        mask_u8 = msk[i].astype(np.uint8) * 255
        contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)

        best = None
        best_area = 0.0
        j = 0
        while j < len(contours):
            a = float(cv2.contourArea(contours[j]))
            if a > best_area:
                best_area = a
                best = contours[j]
            j += 1

        if best is not None and len(best) >= 3:
            poly = best.reshape(-1, 2).astype(int)

            cv2.polylines(vis, [poly], True, (0, 255, 0), 2)
            x, y = int(poly[0][0]), int(poly[0][1])
            cv2.putText(
                vis, f"{name}", (x, y - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2, cv2.LINE_AA
            )

            items.append({"class_name": name, "score": s, "polygon": poly})

        i += 1

    return items, vis


def fps_wait(t0, fps):
    if fps <= 0:
        return time.time()
    dt = time.time() - t0
    per = 1.0 / float(fps)
    if dt < per:
        time.sleep(per - dt)
    return time.time()


def get_carno(cap, pred, meta, allow):
    """
    ✅ 요구사항 반영:
    1) 3자리 나오면 즉시 반환 (프레임 유지 조건 없음)
    2) 1~2자리는 "같은 값이 연속 PARTIAL_MIN_FRAMES 이상"이면 유효(오검 아님)
       유효한 1~2자리가 생긴 뒤,
       MISS_FRAMES 연속 미검출이면 -> "FFF" 반환
    3) 1~2자리가 PARTIAL_MIN_FRAMES 미만으로 잠깐 나오면 -> 오검으로 무시
    """
    cand = ""        # 현재 1~2자리 후보(문자열)
    cand_n = 0       # 후보 연속 프레임 수

    partial_ok = False   # 1~2자리 유효 판정이 한번이라도 났는지
    miss_n = 0           # 유효 판정 후 연속 미검출 프레임 수

    t0 = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            # 영상 끝났는데 3자리 못 찾았으면,
            # 유효 1~2자리 있었으면 FFF, 아니면 FFF(못찾음)로 통일
            return "FFF"

        frame_r = resize_img(frame, TARGET_W, TARGET_H)
        items, vis = infer(pred, frame_r, meta, allow, SCORE_TH)

        digits = sort_digits(items)
        s = "".join(digits)

        # 화면 표시
        cv2.imshow(WINDOW_NAME, vis)
        key = cv2.waitKey(1) & 0xFF
        if key == 27 or key == ord('q'):
            return "FFF"

        # FPS 제한
        t0 = fps_wait(t0, SHOW_FPS)

        # ----- 판정 로직 -----
        if len(s) == 3:
            return s

        if len(s) in (1, 2):
            miss_n = 0

            # 같은 값이 이어지는지 체크
            if s == cand:
                cand_n += 1
            else:
                cand = s
                cand_n = 1

            # PARTIAL_MIN_FRAMES 이상이면 "유효(오검 아님)"
            if cand_n >= int(PARTIAL_MIN_FRAMES):
                partial_ok = True

        else:
            # len==0 또는 4+ 같은 이상치 -> 미검출로 취급
            cand = ""
            cand_n = 0

            if partial_ok:
                miss_n += 1
                if miss_n >= int(MISS_FRAMES):
                    return "FFF"


def run_video():
    pred, meta, allow = setup_detectron(CFG_PATH, WEIGHTS_PATH)

    cap = cv2.VideoCapture(VIDEO_SRC)
    if not cap.isOpened():
        print("[ERROR] VideoCapture open failed:", VIDEO_SRC)
        return

    while True:
        carno = get_carno(cap, pred, meta, allow)

        # get_carno()에서 q/esc 누르면 "FFF" 반환하니까
        # 종료 신호로 쓰고 싶으면 여기서 break 처리
        if carno == "FFF":
            print("[RESULT] FFF")
        else:
            print("[RESULT]", carno)

        # 영상이 끝나면 get_carno가 ret=False에서 "FFF" 반환함
        # 여기서 종료하려면 cap 위치 확인해서 끝이면 break
        pos = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total > 0 and pos >= total:
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    run_video()
