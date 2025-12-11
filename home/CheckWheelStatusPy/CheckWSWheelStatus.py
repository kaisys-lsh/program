# -*- coding: utf-8 -*- 


import os 
import io 
import glob 
import pickle 
import configparser  
import yaml 
import cv2 
import torch 
import numpy as np 
import math
import threading
import time
from collections import deque
from yacs.config import CfgNode 

from detectron2.config import get_cfg 
from detectron2.engine import DefaultPredictor 
from detectron2.data import MetadataCatalog 
from detectron2.utils.visualizer import Visualizer 
from detectron2.projects import point_rend 
from multiprocessing import shared_memory

# ★ 여기 추가
import zmq
import json

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"


class SharedData:
    def __init__(self):
        self.lock = threading.Lock()
        self.value1 = 0
        self.value2 = 0
        self.text  = "init"
        

class RepeatingTimer:
    def __init__(self, interval, callback):
        self.interval = interval      # 초 단위 반복주기
        self.callback = callback      # 실행할 함수
        self.running = False
        self.thread = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self.run)
        self.thread.daemon = True
        self.thread.start()

    def run(self):
        while self.running:
            time.sleep(self.interval)
            self.callback()

    def stop(self):
        self.running = False


shared = SharedData()

# ===== HMI로 휠 상태 보내는 ZMQ 송신 설정 =====
ZMQ_WS_ADDR = "tcp://0.0.0.0:5578"   # 서버가 bind 하므로 0.0.0.0 추천

def create_ws_sender():
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.PUSH)

    # 송신 큐에 메시지가 많이 쌓이지 않도록 제한
    sock.setsockopt(zmq.SNDHWM, 1)

    # ✅ 이제 이 쪽이 bind(PUSH) 하고,
    sock.bind(ZMQ_WS_ADDR)

    print("[ZMQ] WS sender bound:", ZMQ_WS_ADDR)
    return sock



# 1) INI 읽기 
config = configparser.ConfigParser() 
config.read(r'C:\Users\user\Desktop\project\program\home\CheckWheelStatusPy\Config.ini')  # ← raw 문자열 
SEC = 'SYSTEM'
WORK_POS = "WS_POS"
IMG_POP = "Measuring WS-Wheel Status"
config_file_path = config.get(SEC, 'config_file_path') 


# ============== (A) 경로/파라미터 ==============
CFG_PATH                = config.get(SEC, 'cfg_save_path') 
WEIGHTS_PATH            = "./model_final.pth"
METADATA_YAML           = config.get(SEC, 'Metadata_file')
CONF_THRESH             = config.getfloat(SEC, 'InferenceThreshold')
DEVICE                  = "cuda" if torch.cuda.is_available() else "cpu"
DATASET_NAME            = "inference_dataset"  # 메타데이터 등록명
ENCODING                = "utf-8"              # writer와 동일하게
V_URL                   = config.get(WORK_POS, 'URL')
SM_NAME                 = config.get(WORK_POS, 'SM_Name')
SM_SIZE                 = config.getint(WORK_POS, 'SM_Size')
STOP_LSEC               = config.getint(WORK_POS, 'stop_sec') * 2

# 이미지 크기
width                   = config.getint(WORK_POS, 'Img_width')
height                  = config.getint(WORK_POS, 'Img_height')
ROI_X                   = config.getint(WORK_POS, 'roi_x')
ROI_Y                   = config.getint(WORK_POS, 'roi_y')
ROI_W                   = config.getint(WORK_POS, 'roi_w')
ROI_H                   = config.getint(WORK_POS, 'roi_h')

channels = 4  # BGRA
frame_size = width * height * channels
roi = (ROI_X, ROI_Y, ROI_W, ROI_H)      # DS  (x, y, w, h)  ← 직접 지정 (원하면 None) # WS  (x, y, w, h)  ← 직접 지정 (원하면 None)


def get_shared_memory():
    try:
        # 1) 먼저 기존 공유메모리를 열어본다
        shm = shared_memory.SharedMemory(name=SM_NAME, create=False)
        print("기존 공유메모리 참조 성공!")
    except FileNotFoundError:
        # 2) 존재하지 않으면 새로 생성
        shm = shared_memory.SharedMemory(name=SM_NAME, size=SM_SIZE, create=True)
        print("공유메모리 새로 생성!")

    return shm


# 공유메모리 생성
shm = get_shared_memory()
# numpy 배열 view 생성
status_array = np.ndarray((SM_SIZE,), dtype=np.uint8, buffer=shm.buf)
status_array[:] = 0


# ============== (B) 유틸: 메타데이터 로드/등록 ==============
def clamp_roi_to_frame(x, y, w, h, width, height):
    # 프레임 경계 밖을 넘어가면 안전하게 보정
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    w = max(1, min(w, width - x))
    h = max(1, min(h, height - y))
    return x, y, w, h



# ============== (B) 유틸: 메타데이터 로드/등록 ==============
def load_metadata_yaml(yaml_path):
    if yaml_path is None:
        return {}
    if not os.path.exists(yaml_path):
        raise FileNotFoundError("Metadata.yaml 없음: " + yaml_path)
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def apply_metadata(dataset_name, meta_dict):
    meta = MetadataCatalog.get(dataset_name)
    # 클래스명
    if isinstance(meta_dict.get("thing_classes"), list):
        meta.thing_classes = meta_dict["thing_classes"]
    # 색상(선택)
    if isinstance(meta_dict.get("thing_colors"), list):
        meta.thing_colors = meta_dict["thing_colors"]
    # dataset_id -> contiguous 매핑(선택)
    mapping = meta_dict.get("thing_dataset_id_to_contiguous_id")
    if isinstance(mapping, dict):
        fixed = {}
        for k, v in mapping.items():
            try:
                fixed[int(k)] = int(v)
            except Exception:
                pass
        meta.thing_dataset_id_to_contiguous_id = fixed
    return meta


# ============== (C) 유틸: cfg 로드 (YAML/PKL 지원) ==============
def load_cfg(cfg_path):
    cfg = get_cfg()

    if "pointrend" in config_file_path:
        point_rend.add_pointrend_config(cfg)    # PointRend 전용 설정

    ext = os.path.splitext(cfg_path)[1].lower()
    if ext in [".yaml", ".yml"]:
        # 윈도우 인코딩 문제 회피: UTF-8로 강제
        from fvcore.common.config import load_cfg as fv_load_cfg
        with io.open(cfg_path, "r", encoding="utf-8") as f:
            cfg.merge_from_other_cfg(fv_load_cfg(f))
    elif ext in [".pkl", ".pickle"]:
        with open(cfg_path, "rb") as f:
            obj = pickle.load(f)
        if isinstance(obj, CfgNode):
            cfg.merge_from_other_cfg(obj)
        elif isinstance(obj, dict) and isinstance(obj.get("cfg"), CfgNode):
            cfg.merge_from_other_cfg(obj["cfg"])
        else:
            raise ValueError("Pickle 안에 CfgNode가 없습니다. 저장 형식 확인 필요.")
    else:
        raise ValueError("cfg 확장자는 .yaml/.yml/.pkl/.pickle 중 하나여야 합니다.")
    return cfg


# ============== (D) Predictor 빌드 ==============
def build_predictor(cfg_path, weights_path, conf_thresh, device, dataset_name):
    cfg = load_cfg(cfg_path)
    cfg.MODEL.WEIGHTS = weights_path
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = float(conf_thresh)
    cfg.MODEL.DEVICE = device

    # 메타데이터의 클래스 수로 NUM_CLASSES 맞춰주면 안전
    classes = MetadataCatalog.get(dataset_name).get("thing_classes", [])
    if len(classes) > 0:
        cfg.MODEL.ROI_HEADS.NUM_CLASSES = len(classes)
        if "pointrend" in config_file_path:
            cfg.MODEL.POINT_HEAD.NUM_CLASSES = len(classes)   # PointRend용

    predictor = DefaultPredictor(cfg)
    return predictor, cfg


# ============== distance ==============
def distance(a, b):
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return math.sqrt(dx * dx + dy * dy)


# ============== check_hexagon_from_cluster ==============
def check_hexagon_from_cluster(points, cluster_indices, radius_tol_ratio, angle_tol_deg):
    """
    C++: CheckHexagonFromCluster(...)
      - points           : 전체 포인트 리스트
      - cluster_indices  : 이 클러스터에 속한 points의 인덱스 리스트
      - radius_tol_ratio : 반지름 허용 편차 비율 (예: 0.2)
      - angle_tol_deg    : 각도 간격 허용 오차 (예: 15도)

    반환:
      - 육각형으로 판별되면: hex_indices (길이 6짜리 인덱스 리스트)
      - 아니면           : 빈 리스트 []
    """
    n = len(cluster_indices)
    if n < 6:
        return []

    # 1) 클러스터 전체 중심(평균) 계산
    cx = 0.0
    cy = 0.0
    for idx in cluster_indices:
        p = points[idx]
        cx += p[0]
        cy += p[1]

    cx /= float(n)
    cy /= float(n)

    # 2) 각 점의 중심 기준 거리/각도 계산 후, 중심에서 가까운 것 6개 선택
    cand = []  # 각 요소: {"index": idx, "angle": ang, "radius": r}

    for idx in cluster_indices:
        p = points[idx]
        dx = p[0] - cx
        dy = p[1] - cy
        r = math.sqrt(dx * dx + dy * dy)
        ang = math.atan2(dy, dx)  # -pi ~ +pi

        ai = {
            "index": idx,
            "angle": ang,
            "radius": r
        }
        cand.append(ai)

    # 반지름 기준 정렬해서 가까운 6개 선출
    cand.sort(key=lambda ai: ai["radius"])

    if len(cand) > 6:
        cand = cand[:6]

    # 선택된 6개에 대해 평균 반지름
    r_sum = 0.0
    for ai in cand:
        r_sum += ai["radius"]
    r_mean = r_sum / 6.0

    # 반지름이 너무 0이면 이상한 경우
    if r_mean < 1e-6:
        return []

    # 3) 각도 기준 정렬
    cand.sort(key=lambda ai: ai["angle"])

    # 반지름 편차 체크
    for ai in cand:
        diff_r = abs(ai["radius"] - r_mean)
        if diff_r > r_mean * radius_tol_ratio:
            # 반지름 편차가 너무 크면 육각형으로 보기 힘듦
            return []

    # 각도 간격 체크 (이상적인 간격: 360/6 = 60도)
    ideal_deg = 360.0 / 6.0
    for i in range(6):
        j = (i + 1) % 6
        ang_i = cand[i]["angle"]
        ang_j = cand[j]["angle"]

        d_ang = ang_j - ang_i
        if d_ang < 0:
            d_ang += 2.0 * math.pi

        d_deg = d_ang * 180.0 / math.pi
        err_deg = abs(d_deg - ideal_deg)

        if err_deg > angle_tol_deg:
            # 각도 간격이 60도에서 너무 멀어짐
            return []

    # 여기까지 통과하면 "육각형"이라고 판단
    hex_indices = []
    for ai in cand:
        hex_indices.append(ai["index"])

    return hex_indices


# ============== infer_hexagon_from_5points ==============
def infer_hexagon_from_5points(points, cluster_indices, radius_tol_ratio, angle_tol_deg):
    """
    cluster_indices에 '정확히 5개'의 점만 있을 때,
    이것이 거의 정육각형의 5개 꼭짓점이라고 가정하고
    빠진 1개 점을 추정해 6개 좌표를 반환.

    조건에 맞지 않으면 [] 반환.
    """
    if len(cluster_indices) != 5:
        return []

    # 1) 중심 계산 (5점 평균)
    cx = 0.0
    cy = 0.0
    for idx in cluster_indices:
        p = points[idx]
        cx += p[0]
        cy += p[1]

    cx /= 5.0
    cy /= 5.0

    # 2) 각 점의 각도/반지름 계산
    items = []  # {"idx": idx, "angle_deg": ang_deg, "radius": r}
    r_sum = 0.0

    for idx in cluster_indices:
        px, py = points[idx]
        dx = px - cx
        dy = py - cy
        r = math.sqrt(dx * dx + dy * dy)
        if r < 1e-6:
            return []
        ang_rad = math.atan2(dy, dx)  # -pi ~ +pi
        ang_deg = ang_rad * 180.0 / math.pi
        if ang_deg < 0:
            ang_deg += 360.0

        items.append({
            "idx": idx,
            "angle_deg": ang_deg,
            "radius": r
        })
        r_sum += r

    r_mean = r_sum / 5.0
    if r_mean < 1e-6:
        return []

    # 반지름 편차 1차 체크 (5점 자체가 너무 들쭉날쭉이면 탈락)
    for it in items:
        diff_r = abs(it["radius"] - r_mean)
        if diff_r > r_mean * radius_tol_ratio:
            return []

    # 3) 각도 정렬
    items.sort(key=lambda it: it["angle_deg"])

    # 인접 각도 간격 계산 (5개 점 → 간격 5개)
    ideal_deg = 60.0
    gap_list = []  # (gap_deg, i) : i번째와 i+1번째 사이
    for i in range(5):
        j = (i + 1) % 5
        a_i = items[i]["angle_deg"]
        a_j = items[j]["angle_deg"]
        d = a_j - a_i
        if d < 0:
            d += 360.0
        gap_list.append((d, i))

    # 가장 큰 간격(= 빠진 점이 있어야 할 부분)
    max_gap, max_i = max(gap_list, key=lambda g: g[0])

    # 120도 근처인지 검사 (빠진 1개 포함해서 2*60도)
    if abs(max_gap - 2.0 * ideal_deg) > 2.0 * angle_tol_deg:
        return []

    # 나머지 네 간격은 60도 근처인지 검사
    for gap, idx_gap in gap_list:
        if idx_gap == max_i:
            continue
        if abs(gap - ideal_deg) > angle_tol_deg:
            return []

    # 4) 빠진 점의 각도 계산
    a_start = items[max_i]["angle_deg"]
    new_angle_deg = a_start + ideal_deg
    if new_angle_deg >= 360.0:
        new_angle_deg -= 360.0
    new_angle_rad = new_angle_deg * math.pi / 180.0

    # 새 점 반지름은 '큰 간격 양쪽 두 점의 반지름 평균'
    r1 = items[max_i]["radius"]
    r2 = items[(max_i + 1) % 5]["radius"]
    r_new = (r1 + r2) / 2.0

    # 새 점 좌표
    new_x = cx + r_new * math.cos(new_angle_rad)
    new_y = cy + r_new * math.sin(new_angle_rad)

    # 5) 최종 6개 점(기존 5 + 새 1)을 가지고 **한 번 더 육각형 검증**

    hex_pts = []
    for it in items:
        hex_pts.append((points[it["idx"]][0], points[it["idx"]][1]))
    hex_pts.append((new_x, new_y))

    # 5-1) 중심 재계산 (6점 기준)
    cx2 = sum(p[0] for p in hex_pts) / 6.0
    cy2 = sum(p[1] for p in hex_pts) / 6.0

    # 5-2) 반지름/각도 재계산
    radii = []
    angles = []
    for x, y in hex_pts:
        dx = x - cx2
        dy = y - cy2
        r = math.sqrt(dx * dx + dy * dy)
        if r < 1e-6:
            return []
        radii.append(r)
        ang = math.atan2(dy, dx) * 180.0 / math.pi
        if ang < 0:
            ang += 360.0
        angles.append(ang)

    r_mean2 = sum(radii) / 6.0
    if r_mean2 < 1e-6:
        return []

    # 반지름 편차 2차 체크 (6점 모두)
    for r in radii:
        if abs(r - r_mean2) > r_mean2 * radius_tol_ratio:
            # 육각형으로 보기 어려우면 그냥 포기
            return []

    # 각도 정렬 후 간격 체크
    angles.sort()
    gaps6 = []
    for i in range(6):
        j = (i + 1) % 6
        d = angles[j] - angles[i]
        if d < 0:
            d += 360.0
        gaps6.append(d)

    for g in gaps6:
        if abs(g - ideal_deg) > angle_tol_deg:
            # 60도 간격이 아니면 포기
            return []

    # 여기까지 통과하면 6점이 "상당히 정상적인 육각형"이라고 판단
    # 각도 순서대로 정렬해서 반환
    tmp = []
    for (x, y) in hex_pts:
        dx = x - cx2
        dy = y - cy2
        ang = math.atan2(dy, dx) * 180.0 / math.pi
        if ang < 0:
            ang += 360.0
        tmp.append((ang, (x, y)))

    tmp.sort(key=lambda v: v[0])
    hex_pts_sorted = [v[1] for v in tmp]

    return hex_pts_sorted



# ============== find_hexagons ==============
def find_hexagons(points, cluster_radius, radius_tol_ratio, angle_tol_deg):
    """
    파이썬:
      - points:  [(x, y), ...]
      - cluster_radius: 같은 Wheel에 속한다고 볼 최대 거리
      - radius_tol_ratio: 육각형 반지름 허용 편차 비율
      - angle_tol_deg   : 각도 간격 허용 오차

    반환:
      hexagons: [ [ (x1,y1), ..., (x6,y6) ],   # 첫 번째 육각형 (6점 모두 좌표)
                  [ (x1,y1), ..., (x6,y6) ],   # 두 번째 육각형
                  ...
                ]

    ※ 점이 6개인 경우 → 실제 점 6개 사용
       점이 5개인 경우 → 6번째 점을 추정해서 6개로 채움
    """
    hexagons = []

    n = len(points)
    if n < 5:  # 최소 5개는 있어야 5점→6점 보정 가능
        return hexagons

    visited = [False] * n

    # --- 1) 간단한 클러스터링 (반경 clusterRadius 기준) ---
    for i in range(n):
        if visited[i]:
            continue

        # 새로운 클러스터 시작
        cluster_indices = []
        q = deque()

        visited[i] = True
        q.append(i)
        cluster_indices.append(i)

        while len(q) > 0:
            cur = q.popleft()

            for k in range(n):
                if visited[k]:
                    continue

                dist = distance(points[cur], points[k])
                if dist <= cluster_radius:
                    visited[k] = True
                    q.append(k)
                    cluster_indices.append(k)

        # --- 2) 이 클러스터에서 육각형 모양이 나오는지 확인 ---
        if len(cluster_indices) >= 6:
            # 실제 점 6개로 이루어진 육각형 탐색 (기존 로직)
            hex_indices = check_hexagon_from_cluster(
                points,
                cluster_indices,
                radius_tol_ratio,
                angle_tol_deg
            )

            if len(hex_indices) == 6:
                one_hex = []
                for idx in hex_indices:
                    one_hex.append(points[idx])
                hexagons.append(one_hex)

        elif len(cluster_indices) == 5:
            # 점이 5개뿐인 경우: 빠진 1점을 추정해서 6점 완성
            hex_pts = infer_hexagon_from_5points(
                points,
                cluster_indices,
                radius_tol_ratio,
                angle_tol_deg
            )
            if len(hex_pts) == 6:
                hexagons.append(hex_pts)

        # 그 외 (점이 4개 이하) → 육각형 불가, 무시

    return hexagons


# ============== sort_hexagon_points ==============
def sort_hexagon_points(pts):
    """
    pts: [(x, y), (x, y), ...] 형태의 리스트
    다각형(육각형) 점들을 중심 기준 각도 오름차순으로 정렬 (in-place 수정)
    """
    n = len(pts)
    if n < 3:
        return  # 3점 이하는 다각형 아님

    # 1) 중심점(평균) 계산
    cx = 0.0
    cy = 0.0
    for (x, y) in pts:
        cx += x
        cy += y
    cx /= float(n)
    cy /= float(n)

    # 2) 각도 계산해서 (angle, point) 리스트 생성
    angle_points = []
    for (x, y) in pts:
        dx = x - cx
        dy = y - cy
        ang = math.atan2(dy, dx)  # -pi ~ +pi
        angle_points.append((ang, (x, y)))

    # 3) 각도 기준 오름차순 정렬
    angle_points.sort(key=lambda ap: ap[0])

    # 4) 정렬 결과를 pts에 반영 (in-place)
    for i in range(n):
        pts[i] = angle_points[i][1]
        
 

# ============== polygon_centroid ==============
def polygon_centroid(pts):
    """
    pts: [(x, y), ...] 형태의 리스트 (3점 이상)
    다각형의 무게중심(centroid) 반환
    """
    n = len(pts)
    if n < 3:
        return (0.0, 0.0)

    A = 0.0   # signed area
    Cx = 0.0
    Cy = 0.0

    for i in range(n):
        j = (i + 1) % n

        xi, yi = pts[i]
        xj, yj = pts[j]

        cross = xi * yj - xj * yi  # cross product term

        A += cross
        Cx += (xi + xj) * cross
        Cy += (yi + yj) * cross

    A *= 0.5

    # A가 0이면 문제 있는 도형
    if abs(A) < 1e-8:
        return (0.0, 0.0)

    Cx /= (6.0 * A)
    Cy /= (6.0 * A)

    return (Cx, Cy)


# ============== get_angle_deg_from_center ==============
def get_angle_deg_from_center(c, p):
    """
    c: (cx, cy)  중심점
    p: (px, py)  점
    반환: center → pt 방향의 각도 (0~360°)

    C++ 코드 완전 동일 변환:
      - y축 반전 dy = c.y - p.y   (이미지 좌표계 기준)
      - atan2로 방향 계산
      - 오른쪽=0°, 위=90° → 위를 0°로 맞추기: 90 - deg
    """
    cx, cy = c
    px, py = p

    dx = px - cx
    dy = cy - py    # ★ y축 반전 (OpenCV/이미지 좌표용)

    # radian: -pi ~ +pi
    rad = math.atan2(dy, dx)
    deg = rad * 180.0 / math.pi

    if deg < 0:
        deg += 360.0

    # 위를 0도로 맞추기 (C++의 final = 90 - deg)
    final_deg = 90.0 - deg
    if final_deg < 0:
        final_deg += 360.0

    return final_deg



# ============== compute_hexagon_line_angles ==============
def compute_hexagon_line_angles(hex_pts, center):
    """
    hex_pts: [(x1,y1), ..., (x6,y6)]  정렬된 육각형 점들
    center : (cx, cy)
    반환:
        out_lines = [
            { "p1": center, "p2": (x,y), "angle": deg },
            ...
        ]
    """

    out_lines = []

    for pt in hex_pts:
        angle = get_angle_deg_from_center(center, pt)
        line = {
            "p1": center,
            "p2": pt,
            "angle": angle
        }
        out_lines.append(line)

    return out_lines



# ============== (E) 단일 이미지 추론 ==============
def infer_image(predictor, img, dataset_name,
                has_prev,
                vt_pre_angle,
                prev_center_xpos,
                vt_result,
                vt_xpos_delt,
                vt_ypos_delt):
    
    outputs = predictor(img)
    instances = outputs["instances"].to("cpu")

    # 박스, 점수, 클래스ID 추출
    boxes   = instances.pred_boxes.tensor.numpy()   # [N, 4] (x1, y1, x2, y2)
    scores  = instances.scores.numpy()              # [N]
    classes = instances.pred_classes.numpy()        # [N]

    class_names = MetadataCatalog.get(dataset_name).get("thing_classes", [])

    num_detections = len(instances)
    # print("추론 개수:", num_detections)
    
    # 그릴 이미지 복사본
    vis_img = img.copy()
    
    objects = []

    for i in range(num_detections):
        # 점수 기준 필터
        if scores[i] < 0.9:
            continue
        
        cls_id = int(classes[i])
        # class id 범위 체크
        if not (0 <= cls_id < len(class_names)):
            continue
        
        cls_name = class_names[cls_id]
        # 🔴 여기! Bolt 클래스만 유효하게 필터링
        if cls_name != "Bolt":
            continue

        x1 = int(boxes[i][0])
        y1 = int(boxes[i][1])
        x2 = int(boxes[i][2])
        y2 = int(boxes[i][3])
        
        # ─────────────────────────────
        # 박스 중심점 계산
        # ─────────────────────────────
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        objects.append((np.float32(cx), np.float32(cy)))
        
    cluster_radius   = 500.0    # 같은 Wheel로 묶을 거리 기준
    radius_tol_ratio = 0.2      # 반지름 ±20% 허용
    angle_tol_deg    = 15.0     # 각도 간격 ±15도 허용
        
    hexagons = find_hexagons(objects, cluster_radius, radius_tol_ratio, angle_tol_deg)
        
    if len(hexagons) == 1:
        hex_points = hexagons[0].copy()
        sort_hexagon_points(hex_points)
        hexcentrpt = polygon_centroid(hex_points)
            
        line_angles = compute_hexagon_line_angles(hex_points, hexcentrpt)
                        
        if not has_prev:
            vt_pre_angle.clear()
            for la in line_angles:
                vt_pre_angle.append(la["angle"])
            prev_center_xpos = int(hexcentrpt[0])
            vt_ypos_delt.append(int(hexcentrpt[1]))
            has_prev = True
        else:
            dsum = 0.0
            prev_count = len(vt_pre_angle)
            curr_count = len(line_angles)

            if curr_count == prev_count:
                for i in range(prev_count):
                    dsum += abs(vt_pre_angle[i] - line_angles[i]["angle"])
                davg = dsum / curr_count
                vt_result.append(davg)

            vx = abs(prev_center_xpos - int(hexcentrpt[0]))
            vt_xpos_delt.append(vx)
            vt_ypos_delt.append(int(hexcentrpt[1]))
            prev_center_xpos = int(hexcentrpt[0])            
            
        for i in range(len(hex_points)):
            x1, y1 = hex_points[i]
            x2, y2 = hex_points[(i + 1) % len(hex_points)]
            cv2.line(
                vis_img,
                (int(x1), int(y1)),
                (int(x2), int(y2)),
                (0, 255, 0),
                2
            )
            
        cx, cy = hexcentrpt    
        if not (cx == 0.0 and cy == 0.0):
            cv2.circle(
                vis_img,
                (int(cx), int(cy)),
                25,
                (0, 0, 255),
                -1
                )

    return vis_img, outputs, has_prev, vt_pre_angle, prev_center_xpos, vt_result, vt_xpos_delt, vt_ypos_delt, len(hexagons)


# ============== open_capture ==============
def open_capture(rtsp_url):
    """RTSP 스트림을 여는 함수 (버퍼 최소화 버전)"""
    print("[INFO] RTSP 연결 시도:", rtsp_url)

    # FFMPEG 백엔드 사용
    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)

    if not cap.isOpened():
        print("[ERROR] RTSP 연결 실패")
        return None

    # 🟢 내부 버퍼 크기 줄이기 (가능한 경우)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        print("[INFO] CAP_PROP_BUFFERSIZE = 1 설정")
    except Exception as e:
        print("[WARN] CAP_PROP_BUFFERSIZE 설정 실패:", e)

    # 🟢 연결 직후 버퍼에 남아 있을 수 있는 오래된 프레임 몇 개 버리기
    throw_cnt = 0
    while throw_cnt < 3:
        cap.read()
        throw_cnt += 1

    print("[INFO] RTSP 연결 성공")
    return cap



def write_wheel_status(
        status_array,
        car_no_str,
        wheel_1st_rotate_state,
        wheel_1st_pos_state,
        wheel_2nd_rotate_state,
        wheel_2nd_pos_state,
        block=True,
        timeout_sec=None,
        poll_interval=0.01
    ):
    """
    Wheel 상태 쓰기.
    - car_no_str: 3자리 문자열 (위 대차번호와 동일 형식)
    - wheel_1st_rotate_state: 0: 감지 실패 / 1: 회전 / 2: 무회전
    - wheel_1st_pos_state:    0: 감지 실패 / 1: 정상 / 2: 비정상
    - wheel_2nd_rotate_state: 0: 감지 실패 / 1: 회전 / 2: 무회전
    - wheel_2nd_pos_state:    0: 감지 실패 / 1: 정상 / 2: 비정상

    - 규칙: status_array[10] == 0 일 때만 새 값 기록 후 status_array[10] = 1
    """

    # 대차 번호 문자열 정리 (3자리를 맞춰줌)
    s = str(car_no_str)
    if len(s) >= 3:
        digits = s[:3]
    else:
        digits = s.zfill(3)

    start_time = time.time()

    # 상대방(HMI)이 이전 값을 아직 안 읽어갔으면 기다림
    while True:
        flag = status_array[10]
        if flag == 0:
            break

        if not block:
            print("대차 Wheel 상태 공유 실패..!! (flag=1, block=False)")
            return False

        if timeout_sec is not None:
            now = time.time()
            if now - start_time > timeout_sec:
                print("대차 Wheel 상태 공유 실패..!! (timeout)")
                return False

        time.sleep(poll_interval)

    # 11~13번: 대차 번호 ASCII
    i = 0
    while i < 3:
        status_array[11 + i] = ord(digits[i])
        i += 1

    # 14~15 Reserved 0
    status_array[14] = 0
    status_array[15] = 0

    # 16~17: 1st 대차 wheel 상태 값
    status_array[16] = int(wheel_1st_rotate_state)   # 회전 상태
    status_array[17] = int(wheel_1st_pos_state)      # 위치 상태

    # 18~19 Reserved 0
    status_array[18] = 0
    status_array[19] = 0

    # 20~21: 2nd 대차 wheel 상태 값
    status_array[20] = int(wheel_2nd_rotate_state)   # 회전 상태
    status_array[21] = int(wheel_2nd_pos_state)      # 위치 상태

    # 22~23 Reserved 0
    status_array[22] = 0
    status_array[23] = 0

    # 마지막에 Flag = 1 (새 상태 도착)
    status_array[10] = 1
    print("대차 Wheel 상태 공유 성공..!!")
    return True




def TimeTick():
    # 타이머 스레드에서 공유메모리 접근 
    with shared.lock:
        if shared.value1:
            shared.value2 += 1
            WheelstopCnt = shared.value2
        else:
            WheelstopCnt = shared.value2 = 0
    
    if WheelstopCnt >= STOP_LSEC:
        if not status_array[0]:
            status_array[0] = 1
            
    else:
        if status_array[0]:
            status_array[0] = 0
            


def main():
    Wheel_1st_Position_Status = 0
    Wheel_2nd_Position_Status = 0    
    Wheel_Rotation_Status = 0
    prev_Wheel_Move_Flag = False
    prev_Wheel_1st_Rotation_Status = 0
    prev_Wheel_2nd_Rotation_Status = 0
    prev_Wheel_1st_Position_Status = 0
    prev_Wheel_2nd_Position_Status = 0
    Text_Wheel_Move = "Car Movement : Moved"
    Text_1st_Wheel_Rotation = ""
    Text_2nd_Wheel_Rotation = ""
    Text_1st_Wheel_Position = ""
    Text_2nd_Wheel_Position = ""
    Text_Wheel_Number = ""
    Text_Recv_Wheel_Number = ["RECV Car No. : ", "RECV Car No. : ", "RECV Car No. : "]
    
    DectedOkFlag = False
    has_prev = False
    vt_pre_angle = []
    vt_result = []
    vt_xpos_delt = []
    vt_ypos_delt = []
    
    Wheel_Detect_Cnt = 0
    Wheel_Num_Detect_Cnt = 0
    WheelNums = ["FFF", "FFF", "FFF"]
    WheelPosOK_Arr = np.array([0, 0, 0, 0], dtype=np.int8)
    WheelRotation_Arr = np.array([0, 0, 0, 0], dtype=np.int8)
    WheelCenterPos_Arr = np.array([0, 0, 0, 0], dtype=np.int32)
    
    prev_center_xpos = 0
    DetectOffCnt = 0
    xposDeltAvg = 0.0
    ypos1stDeltsum = 0
    ypos2ndDeltsum = 0
    angleAvg = 0.0

    # WS 영상/상태 송신 소켓 생성
    try:
        ws_sock = create_ws_sender()
    except Exception as e:
        print("[ZMQ] WS sender create error:", e)
        ws_sock = None

        
    cap = None
    fail_count = 0
    max_fail_count = 30   # 연속 실패 프레임 수 (예: 30번 연속 read 실패하면 재접속)
    reconnect_delay = 3   # 재접속 전에 대기 시간 (초)  
        
    # 1) 메타데이터 로드/등록
    meta_dict = load_metadata_yaml(METADATA_YAML)
    apply_metadata(DATASET_NAME, meta_dict)
    class_names = MetadataCatalog.get(DATASET_NAME).get("thing_classes", [])

    # 2) Predictor
    predictor, cfg = build_predictor(CFG_PATH, WEIGHTS_PATH, CONF_THRESH, DEVICE, DATASET_NAME)    
    
    while True:
        # 공유 메모리 확인
        if status_array[1] == 0x1:
           # 새로운 대차 번호 도착
           chars = []
           for i in range(3):
                v = shm.buf[2 + i]
                ch = chr(v)
                chars.append(ch)
         
           if Wheel_Num_Detect_Cnt >= 3:
               Wheel_Num_Detect_Cnt = 2
               for i in range(2):
                    WheelNums[i] = WheelNums[i+1]
                    Text_Recv_Wheel_Number[i] = "RECV No. : " + WheelNums[i+1]
                    
           WheelNums[Wheel_Num_Detect_Cnt] = "".join(chars)
           Text_Recv_Wheel_Number[Wheel_Num_Detect_Cnt] = "RECV No. : " + WheelNums[Wheel_Num_Detect_Cnt]
           Wheel_Num_Detect_Cnt += 1
           
           # 새로운 대차 번호 처리 완료 플래그 클리어
           status_array[1] = 0x0
                
        
        # 1) 캡쳐 객체가 없거나 닫혀 있으면 새로 연다
        if cap is None or not cap.isOpened():
            cap = open_capture(V_URL)
            if cap is None:
                # 연결 실패
                time.sleep(reconnect_delay)
                continue
            
            with shared.lock:
                shared.value1 = 0
                shared.value2 = 0
                
            timer = RepeatingTimer(0.5, TimeTick)  # 1초마다 tick() 실행
            timer.start()
            
            fail_count = 0
            has_prev = False
            Wheel_Detect_Cnt = 0
            Wheel_Num_Detect_Cnt = 0
            for i in range(4):
                WheelPosOK_Arr[i] = 0
                WheelRotation_Arr[i] = 0
                WheelCenterPos_Arr[i] = 0
            
        
        # 2) 프레임 읽기
        ret, frame = cap.read()
        if not ret or frame is None:
            fail_count += 1
            # 연속 실패 횟수가 일정 이상이면 재접속
            if fail_count >= max_fail_count:
                print("[WARN] 프레임 읽기 연속 실패, 재접속 시도")
                cap.release()
                cap = None
                time.sleep(reconnect_delay)
                time.sleep(1)
                timer.stop()
                
            else:
                # 잠깐 대기 후 다시 시도 (너무 바쁘게 돌지 않도록)
                time.sleep(0.1)

            continue

        # 여기까지 오면 정상 프레임
        fail_count = 0
        
        # ROI
        x, y, w, h = roi
        H, W = frame.shape[:2]

        if x < 0: x = 0
        if y < 0: y = 0
        if x + w > W: w = W - x
        if y + h > H: h = H - y

        crop = frame[y:y + h, x:x + w]
        
        vis_img, outputs, has_prev, vt_pre_angle, prev_center_xpos, vt_result, vt_xpos_delt, vt_ypos_delt, hax_detections = infer_image(predictor, crop, DATASET_NAME,
                                                                                                                                       has_prev,
                                                                                                                                       vt_pre_angle,
                                                                                                                                       prev_center_xpos,
                                                                                                                                       vt_result,
                                                                                                                                       vt_xpos_delt,
                                                                                                                                       vt_ypos_delt)
        
        
        # print("추론 개수:", hax_detections)
        
        if not hax_detections:
            with shared.lock:
                shared.value1 = 1
            
            DetectOffCnt += 1
            if DetectOffCnt > 30:
                DetectOffCnt = 0
                                
                if DectedOkFlag:
                    DectedOkFlag = False                    
                    Wheel_1st_Position_Status = 0
                    Wheel_2nd_Position_Status = 0
                    Wheel_Rotation_Status = 0
                    xposDeltAvg = 0.0
                    ypos1stDeltsum = 0
                    ypos2ndDeltsum = 0
                    
                    n_result_cnt = len(vt_result)
                    dsum = 0.0
                    for ii in range(n_result_cnt):
                        dsum += vt_result[ii]
                    
                    Wheel_Rotation_Status = 2
                    angleAvg = dsum / n_result_cnt
                    print(f"angleAvg = [{angleAvg}]")
                    if angleAvg > 25.0:
                        Wheel_Rotation_Status = 1
                        
                    # YposDelta 처리
                    n_result_cnt = len(vt_ypos_delt)
                    sum_y = 0
                    for ii in range(n_result_cnt):
                        sum_y += vt_ypos_delt[ii]
                    
                    WheelCenterPos_Arr[Wheel_Detect_Cnt] = sum_y / n_result_cnt
                    print(f"YposDeltAvg = [{WheelCenterPos_Arr[Wheel_Detect_Cnt]}]")
                    
                    WheelPosOK_Arr[Wheel_Detect_Cnt] = 0
                    WheelRotation_Arr[Wheel_Detect_Cnt] = Wheel_Rotation_Status
                    Wheel_Detect_Cnt += 1
                    
                    if Wheel_Detect_Cnt >= 3:
                        Wheel_1st_Position_Status = 1
                        Wheel_2nd_Position_Status = 1
                        ypos2ndDeltsum = abs(WheelCenterPos_Arr[Wheel_Detect_Cnt - 2] - WheelCenterPos_Arr[Wheel_Detect_Cnt - 1])
                        if ypos2ndDeltsum >= 80:
                            Wheel_2nd_Position_Status = 2
                        ypos1stDeltsum = abs(WheelCenterPos_Arr[Wheel_Detect_Cnt - 3] - WheelCenterPos_Arr[Wheel_Detect_Cnt - 2])
                        if ypos1stDeltsum >= 80:
                            Wheel_1st_Position_Status = 2
                        
                        Text_Wheel_Number = "No. " + WheelNums[0]
                        
                        if WheelRotation_Arr[Wheel_Detect_Cnt - 3] != prev_Wheel_1st_Rotation_Status:
                            prev_Wheel_1st_Rotation_Status = WheelRotation_Arr[Wheel_Detect_Cnt - 3]
                            
                            Text_1st_Wheel_Rotation = "1st Wheel Rotation : Fail"
                            if prev_Wheel_1st_Rotation_Status > 0:
                                if prev_Wheel_1st_Rotation_Status == 1:
                                    Text_1st_Wheel_Rotation = "1st Wheel Rotation : Good"
                                else:
                                    Text_1st_Wheel_Rotation = "1st Wheel Rotation : Bad"
                        
                        
                        if WheelRotation_Arr[Wheel_Detect_Cnt - 2] != prev_Wheel_2nd_Rotation_Status:
                            prev_Wheel_2nd_Rotation_Status = WheelRotation_Arr[Wheel_Detect_Cnt - 2]
                            
                            Text_2nd_Wheel_Rotation = "2nd Wheel Rotation : Fail"
                            if prev_Wheel_2nd_Rotation_Status > 0:
                                if prev_Wheel_2nd_Rotation_Status == 1:
                                    Text_2nd_Wheel_Rotation = "2nd Wheel Rotation : Good"
                                else:
                                    Text_2nd_Wheel_Rotation = "2nd Wheel Rotation : Bad"
                        
                        
                        if Wheel_Num_Detect_Cnt:                            
                            WheelPosOK_Arr[Wheel_Detect_Cnt - 2] = Wheel_2nd_Position_Status
                            WheelPosOK_Arr[Wheel_Detect_Cnt - 3] = Wheel_1st_Position_Status
                            write_wheel_status(
                                status_array,
                                WheelNums[0],
                                WheelRotation_Arr[Wheel_Detect_Cnt - 3],
                                WheelPosOK_Arr[Wheel_Detect_Cnt - 3],
                                WheelRotation_Arr[Wheel_Detect_Cnt - 2],
                                WheelPosOK_Arr[Wheel_Detect_Cnt - 2],
                                False
                            )              
                            
                            if Wheel_1st_Position_Status != prev_Wheel_1st_Position_Status:
                                prev_Wheel_1st_Position_Status = Wheel_1st_Position_Status
                                
                                Text_1st_Wheel_Position = "1st Wheel Position : Fail"
                                if prev_Wheel_1st_Position_Status > 0:
                                    if prev_Wheel_1st_Position_Status == 1:
                                        Text_1st_Wheel_Position = "1st Wheel Position : Good"
                                    else:
                                        Text_1st_Wheel_Position = "1st Wheel Position : Bad"
                            
                            
                            if Wheel_2nd_Position_Status != prev_Wheel_2nd_Position_Status:
                                prev_Wheel_2nd_Position_Status = Wheel_2nd_Position_Status
                                
                                Text_2nd_Wheel_Position = "2nd Wheel Position : Fail"
                                if prev_Wheel_2nd_Position_Status > 0:
                                    if prev_Wheel_2nd_Position_Status == 1:
                                        Text_2nd_Wheel_Position = "2nd Wheel Position : Good"
                                    else:
                                        Text_2nd_Wheel_Position = "2nd Wheel Position : Bad"
                            
                            
                            for i in range(2):
                                WheelNums[i] = WheelNums[i+1]
                                Text_Recv_Wheel_Number[i] = "RECV No. : " + WheelNums[i+1]
                            
                            WheelNums[2] = ""
                            Wheel_Num_Detect_Cnt -= 1
                                        
                        WheelPosOK_Arr[0] = WheelPosOK_Arr[Wheel_Detect_Cnt - 1]
                        WheelRotation_Arr[0] = WheelRotation_Arr[Wheel_Detect_Cnt - 1]
                        WheelCenterPos_Arr[0] = WheelCenterPos_Arr[Wheel_Detect_Cnt - 1]                            
                        Text_Recv_Wheel_Number[0] = Text_Recv_Wheel_Number[Wheel_Detect_Cnt - 1]
                        Wheel_Detect_Cnt = 1
                    
                    # 리스트 초기화
                    vt_result.clear()
                    vt_xpos_delt.clear()
                    vt_ypos_delt.clear()
                    # 플래그 초기화
                    has_prev = False
                    print("--> 추론 Reset:")
                                       
            
        else:
            with shared.lock:
                shared.value1 = 0
            
            DetectOffCnt = 0
            if not DectedOkFlag:
                n_result_cnt = len(vt_result)
                if n_result_cnt > 10:
                    DectedOkFlag = True
                    print("--> 추론 Start:")
                    prev_Wheel_1st_Rotation_Status = 0
                    prev_Wheel_2nd_Rotation_Status = 0
                    prev_Wheel_1st_Position_Status = 0
                    prev_Wheel_2nd_Position_Status = 0
                    Text_1st_Wheel_Rotation = "1st Wheel Rotation : Measuring..."
                    Text_2nd_Wheel_Rotation = "2nd Wheel Rotation : Measuring..."
                    Text_1st_Wheel_Position = "1st Wheel Position : Measuring..."
                    Text_2nd_Wheel_Position = "2nd Wheel Position : Measuring..."
                    Text_Wheel_Number = "No. ???"
            else:
                n_result_cnt = len(vt_xpos_delt)
                if n_result_cnt > 300:
                    # 리스트 초기화
                    vt_result.clear()
                    vt_xpos_delt.clear()
                    vt_ypos_delt.clear()
                    # 플래그 초기화
                    has_prev = False
                
                else:
                    if n_result_cnt % 20 == 0:
                        sum_x = 0
                        for ii in range(n_result_cnt):
                            sum_x += vt_xpos_delt[ii]
                    
                        xposDeltAvg = sum_x / n_result_cnt
                        if xposDeltAvg > 2.0:
                            if status_array[0]:
                                status_array[0] = 0
                        else:
                            if not status_array[0]:
                                status_array[0] = 1
                        
                        with shared.lock:
                            shared.value1 = 0
        
        
        if status_array[0]:
            if not prev_Wheel_Move_Flag:
                prev_Wheel_Move_Flag = True
                Text_Wheel_Move = "Car Movement : Stoped"
        else:
            if prev_Wheel_Move_Flag:
                prev_Wheel_Move_Flag = False
                Text_Wheel_Move = "Car Movement : Moved"
                 
       
        cv2.putText(
                vis_img,
                Text_Wheel_Number,
                (50, 30),                        # 좌표 (x, y)
                cv2.FONT_HERSHEY_SIMPLEX,        # 폰트 종류
                1.0,                             # 글자 크기(scale)
                (255, 255, 255),                 # 글자 색 (B, G, R)
                2,                               # 두께
                cv2.LINE_AA                      # 라인 타입 (안티에일리어싱)
            )        
                
        cv2.putText(
                vis_img,
                Text_Wheel_Move,
                (50, 60),                        # 좌표 (x, y)
                cv2.FONT_HERSHEY_SIMPLEX,        # 폰트 종류
                1.0,                             # 글자 크기(scale)
                (255, 255, 255),                 # 글자 색 (B, G, R)
                2,                               # 두께
                cv2.LINE_AA                      # 라인 타입 (안티에일리어싱)
            )     
                    
        cv2.putText(
                vis_img,
                Text_1st_Wheel_Position,
                (50, 100),                       # 좌표 (x, y)
                cv2.FONT_HERSHEY_SIMPLEX,        # 폰트 종류
                1.0,                             # 글자 크기(scale)
                (255, 255, 0),                     # 글자 색 (B, G, R)
                2,                               # 두께
                cv2.LINE_AA                      # 라인 타입 (안티에일리어싱)
            )
                
        cv2.putText(
                vis_img,
                Text_1st_Wheel_Rotation,
                (50, 130),                       # 좌표 (x, y)
                cv2.FONT_HERSHEY_SIMPLEX,        # 폰트 종류
                1.0,                             # 글자 크기(scale)
                (255, 255, 0),                     # 글자 색 (B, G, R)
                2,                               # 두께
                cv2.LINE_AA                      # 라인 타입 (안티에일리어싱)
            )
        
        
        cv2.putText(
                vis_img,
                Text_2nd_Wheel_Position,
                (50, 160),                        # 좌표 (x, y)
                cv2.FONT_HERSHEY_SIMPLEX,        # 폰트 종류
                1.0,                             # 글자 크기(scale)
                (0, 255, 0),                     # 글자 색 (B, G, R)
                2,                               # 두께
                cv2.LINE_AA                      # 라인 타입 (안티에일리어싱)
            )
                
        cv2.putText(
                vis_img,
                Text_2nd_Wheel_Rotation,
                (50, 190),                       # 좌표 (x, y)
                cv2.FONT_HERSHEY_SIMPLEX,        # 폰트 종류
                1.0,                             # 글자 크기(scale)
                (0, 255, 0),                     # 글자 색 (B, G, R)
                2,                               # 두께
                cv2.LINE_AA                      # 라인 타입 (안티에일리어싱)
            )
        
        
        cv2.putText(
                vis_img,
                Text_Recv_Wheel_Number[0],
                (50, ROI_H - 90),                # 좌표 (x, y)
                cv2.FONT_HERSHEY_SIMPLEX,        # 폰트 종류
                1.0,                             # 글자 크기(scale)
                (0, 255, 0),                     # 글자 색 (B, G, R)
                2,                               # 두께
                cv2.LINE_AA                      # 라인 타입 (안티에일리어싱)
            )
        
        cv2.putText(
                vis_img,
                Text_Recv_Wheel_Number[1],
                (50, ROI_H - 60),                # 좌표 (x, y)
                cv2.FONT_HERSHEY_SIMPLEX,        # 폰트 종류
                1.0,                             # 글자 크기(scale)
                (0, 255, 0),                     # 글자 색 (B, G, R)
                2,                               # 두께
                cv2.LINE_AA                      # 라인 타입 (안티에일리어싱)
            )
        
        cv2.putText(
                vis_img,
                Text_Recv_Wheel_Number[2],
                (50, ROI_H - 30),                # 좌표 (x, y)
                cv2.FONT_HERSHEY_SIMPLEX,        # 폰트 종류
                1.0,                             # 글자 크기(scale)
                (0, 255, 0),                     # 글자 색 (B, G, R)
                2,                               # 두께
                cv2.LINE_AA                      # 라인 타입 (안티에일리어싱)
            )
        
        
        resized = cv2.resize(vis_img, (640, 480), interpolation=cv2.INTER_LINEAR)
        cv2.imshow(IMG_POP, resized)
        cv2.waitKey(1)


        # =============================
        # WS 영상 + 상태 ZMQ 전송
        # =============================
        if ws_sock is not None:
            try:
                # 1) JPEG 압축 (영상 전송)
                ok, jpg = cv2.imencode(".jpg", vis_img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ok:
                    frame_bytes = jpg.tobytes()
                else:
                    frame_bytes = b""

                # 2) 상태 JSON 패킷
                ws_status = {
                    "type": "wheel_status",
                    "pos": "WS",
                    "car_no": WheelNums[0],
                    "wheel_1st_rotation": int(WheelRotation_Arr[Wheel_Detect_Cnt - 3]) if Wheel_Detect_Cnt >= 3 else 0,
                    "wheel_1st_position": int(WheelPosOK_Arr[Wheel_Detect_Cnt - 3]) if Wheel_Detect_Cnt >= 3 else 0,
                    "wheel_2nd_rotation": int(WheelRotation_Arr[Wheel_Detect_Cnt - 2]) if Wheel_Detect_Cnt >= 2 else 0,
                    "wheel_2nd_position": int(WheelPosOK_Arr[Wheel_Detect_Cnt - 2]) if Wheel_Detect_Cnt >= 2 else 0,
                }

                # 3) 멀티파트 ZMQ 전송 (영상 + JSON)
                # 🔥 논블로킹으로 보내고, 큐가 꽉 차면 해당 프레임은 버린다
                ws_sock.send_multipart(
                    [frame_bytes, json.dumps(ws_status).encode("utf-8")],
                    flags=zmq.NOBLOCK
                )

            except zmq.Again:
                # 큐가 꽉 차서 지금은 못 보냄 → 이 프레임은 그냥 버린다
                pass

            except Exception as e:
                print("[ZMQ] WS send error:", e)

    # ==== while True 끝난 뒤 (실제 종료 시점) ====
    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()
    shm.close()
    # shm.unlink()  # 필요하면 여기서 실제로 삭제



if __name__ == "__main__":
    main()
    