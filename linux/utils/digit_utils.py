# digit_utils.py
# --------------------------------------------------
# 숫자 검출 결과에서 "3자리 코드"를 안정적으로 만들기 위한 유틸
# 핵심: (1) 같은 줄(y)로 보이는 3개를 먼저 고르고 (2) 그 3개를 x로 정렬
#      3개를 확신할 때만 "XYZ" 반환, 아니면 "NONE"
# --------------------------------------------------

import numpy as np
import torch
from itertools import combinations

from config import config


def decode_label_char(cls_id, metadata):
    """
    클래스 id -> 한 자리 문자로 변환.
    - metadata.thing_classes 가 있으면 해당 라벨의 마지막 글자를 사용
      예) "num_3" → '3'
    - 없으면 id 숫자를 문자열로 그대로 사용.
    """
    label = ""

    if metadata is not None and hasattr(metadata, "thing_classes"):
        if 0 <= cls_id < len(metadata.thing_classes):
            label = metadata.thing_classes[cls_id]

    if not label:
        label = str(cls_id)

    return label[-1]


def filter_digit_region(instances, img_h, img_w):
    """
    위쪽 잡문자/오검을 줄이기 위해,
    숫자가 나오는 대략적인 세로/크기 범위로 필터링한다.
    """
    if len(instances) == 0:
        return instances

    boxes = instances.pred_boxes.tensor.detach().cpu().numpy()

    # 중심 y 좌표, 높이
    yc = (boxes[:, 1] + boxes[:, 3]) * 0.5
    h = boxes[:, 3] - boxes[:, 1]

    # 세로 위치 필터
    y_min = img_h * config.ROI_Y_MIN_RATIO
    y_max = img_h * config.ROI_Y_MAX_RATIO
    mask_y = (yc >= y_min) & (yc <= y_max)

    # 높이 기반 필터 (너무 작거나 너무 큰 것 제거)
    if float(h.mean()) > 0:
        h_mean = float(h.mean())
        mask_h = (h >= h_mean * 0.5) & (h <= h_mean * 1.8)
    else:
        mask_h = np.ones_like(h, dtype=bool)

    keep = mask_y & mask_h

    if not keep.any():
        empty_indices = np.empty((0,), dtype=np.int64)
        empty_indices_t = torch.from_numpy(empty_indices).to(instances.pred_boxes.device)
        return instances[empty_indices_t]

    keep_indices = np.nonzero(keep)[0]
    keep_indices_t = torch.from_numpy(keep_indices).to(instances.pred_boxes.device)
    return instances[keep_indices_t]


def sort_by_x(instances):
    """
    bbox x-center 기준으로 왼쪽→오른쪽 정렬.
    """
    if len(instances) == 0:
        return instances

    boxes = instances.pred_boxes.tensor
    centers = (boxes[:, 0] + boxes[:, 2]) / 2.0
    order = torch.argsort(centers)
    return instances[order]


def pick_best_row_triplet(instances):
    """
    같은 줄(y)로 보이는 후보들 중에서 '가장 그럴듯한 3개'를 선택해서
    x 기준으로 정렬된 Instances(길이 3)를 반환.
    - y 그룹핑: bbox 중심 y가 y_tol 이내면 같은 줄로 묶음
    - 그룹 내: 점수 상위 K개만 보고 3개 조합 중 점수합 최대 선택
    """
    if len(instances) < 3:
        return None

    device = instances.pred_boxes.device

    boxes = instances.pred_boxes.tensor.detach().cpu().numpy()
    scores = instances.scores.detach().cpu().numpy()

    xc = (boxes[:, 0] + boxes[:, 2]) * 0.5
    yc = (boxes[:, 1] + boxes[:, 3]) * 0.5
    h = (boxes[:, 3] - boxes[:, 1])

    avg_h = float(h.mean()) if len(h) > 0 and float(h.mean()) > 0 else 1.0
    y_tol = avg_h * 0.5  # 같은 줄이라고 볼 y 허용 오차

    # y 기준 그룹핑 (greedy)
    order_y = np.argsort(yc)
    groups = []
    for i in order_y:
        i = int(i)
        placed = False
        for g in groups:
            g_mean_y = float(np.mean(yc[g]))
            if abs(float(yc[i]) - g_mean_y) <= y_tol:
                g.append(i)
                placed = True
                break
        if not placed:
            groups.append([i])

    best_trip = None
    best_sum = -1.0

    for g in groups:
        if len(g) < 3:
            continue

        # 그룹 내 점수 상위 K개만 후보로 (조합 폭발 방지)
        g_sorted = sorted(g, key=lambda idx: float(scores[idx]), reverse=True)
        K = min(6, len(g_sorted))
        cand = g_sorted[:K]

        for trip in combinations(cand, 3):
            ssum = float(scores[list(trip)].sum())
            if ssum > best_sum:
                best_sum = ssum
                best_trip = list(trip)

    if best_trip is None:
        return None

    # 선택된 3개를 x 기준으로 정렬
    best_trip = sorted(best_trip, key=lambda idx: float(xc[idx]))
    idx_t = torch.tensor(best_trip, dtype=torch.long, device=device)
    return instances[idx_t]


def build_code_if_exact_3(instances, metadata):
    """
    최종 출력:
    - 3개가 같은 줄로 잘 잡혔다고 판단될 때만 "XYZ"
    - 그 외는 "NONE"
    """
    best3 = pick_best_row_triplet(instances)
    if best3 is None or len(best3) != 3:
        return "NONE"

    best3 = sort_by_x(best3)

    chars = []
    i = 0
    while i < 3:
        cls_id = int(best3.pred_classes[i])
        chars.append(decode_label_char(cls_id, metadata))
        i += 1

    return "".join(chars)
