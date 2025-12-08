# digit_utils.py
# --------------------------------------------------
# 숫자 / 마크 관련 유틸 함수들
# --------------------------------------------------

import numpy as np
import torch

from config import config 


def decode_label_char(cls_id, metadata):
    """
    클래스 id -> 한 자리 문자로 변환.
    - metadata.things_classes 가 있으면 해당 라벨의 마지막 글자를 사용
      예) "num_3" → '3'
    - 없으면 id 숫자를 문자열로 그대로 사용.
    """
    label = ""

    if metadata is not None and hasattr(metadata, "thing_classes"):
        if cls_id >= 0 and cls_id < len(metadata.thing_classes):
            label = metadata.thing_classes[cls_id]

    if not label:
        label = str(cls_id)

    # label 이 "num_3"라면 마지막 글자 '3' 사용
    ch = label[-1]
    return ch


def filter_digit_region(instances, img_h, img_w):
    """
    위쪽 잡문자/오검을 줄이기 위해,
    숫자가 나오는 대략적인 세로/크기 범위로 필터링한다.
    """
    if len(instances) == 0:
        return instances

    boxes = instances.pred_boxes.tensor.numpy()

    # 중심 y 좌표, 높이
    yc = (boxes[:, 1] + boxes[:, 3]) * 0.5
    h = boxes[:, 3] - boxes[:, 1]

    # 세로 위치 필터
    y_min = img_h * config.ROI_Y_MIN_RATIO
    y_max = img_h * config.ROI_Y_MAX_RATIO
    mask_y = (yc >= y_min) & (yc <= y_max)

    # 높이 기반 필터 (너무 작거나 너무 큰 것 제거)
    if h.mean() > 0:
        h_mean = h.mean()
        mask_h = (h >= h_mean * 0.5) & (h <= h_mean * 1.8)
    else:
        mask_h = np.ones_like(h, dtype=bool)

    keep = mask_y & mask_h

    if not keep.any():
        # 전부 걸러진 경우 빈 Instances 반환
        empty_indices = np.empty((0,), dtype=np.int64)
        empty_indices_t = torch.from_numpy(empty_indices).to(instances.pred_boxes.device)
        return instances[empty_indices_t]

    keep_indices = np.nonzero(keep)[0]
    keep_indices_t = torch.from_numpy(keep_indices).to(instances.pred_boxes.device)
    return instances[keep_indices_t]


def sort_by_x(instances):
    """
    bounding box 의 x 중심 기준으로 왼쪽→오른쪽 정렬.
    """
    if len(instances) == 0:
        return instances

    boxes = instances.pred_boxes.tensor
    centers = (boxes[:, 0] + boxes[:, 2]) / 2.0
    order = torch.argsort(centers)
    return instances[order]


def init_slots():
    """
    100, 10, 1의 자리용 슬롯 3개 초기화.
    각 슬롯은 dict 로 관리:
    {
        "char":  None or 문자,
        "score": 0.0,
        "x":     None,
        "y":     None
    }
    """
    slots = []

    index = 0
    while index < 3:
        slot = {
            "char": None,
            "score": 0.0,
            "x": None,
            "y": None,
        }
        slots.append(slot)
        index += 1

    return slots


def update_slots_with_instances(slots, instances, metadata):
    """
    현재 프레임의 숫자 Instances 를 왼쪽→오른쪽 정렬해서
    최대 3개까지 슬롯(100, 10, 1 자리)에 매칭.
    각 슬롯 내에서 score 가 더 높은 숫자로 교체한다.
    슬롯 위치 자체는 고정된 3개이며, 자리 재배치는 하지 않는다.
    """
    if len(instances) == 0:
        return

    inst_sorted = sort_by_x(instances)
    boxes = inst_sorted.pred_boxes.tensor.numpy()
    scores = inst_sorted.scores.cpu().numpy()

    ys = (boxes[:, 1] + boxes[:, 3]) * 0.5
    heights = boxes[:, 3] - boxes[:, 1]

    if len(heights) > 0:
        avg_h = heights.mean()
    else:
        avg_h = 1.0

    y_tol = avg_h * 0.5  # y 축 허용 오차(같은 줄이라고 볼 수 있는 범위)

    max_slots = 3
    num_instances = len(inst_sorted)

    idx = 0
    while idx < max_slots and idx < num_instances:
        cls_id = int(inst_sorted.pred_classes[idx])
        ch = decode_label_char(cls_id, metadata)
        score = float(scores[idx])

        x1 = boxes[idx][0]
        y1 = boxes[idx][1]
        x2 = boxes[idx][2]
        y2 = boxes[idx][3]

        xc = 0.5 * (x1 + x2)
        yc = 0.5 * (y1 + y2)

        slot = slots[idx]  # 왼쪽→오른쪽 순서대로 0,1,2 슬롯 사용

        # 같은 슬롯 안에서 y 위치가 너무 다르면 다른 줄이라고 판단하고 무시
        if slot["char"] is not None and slot["y"] is not None:
            if abs(yc - slot["y"]) > y_tol:
                idx += 1
                continue

        # score 가 더 좋은 경우에만 갱신
        if score >= slot["score"]:
            slot["char"] = ch
            slot["score"] = score
            slot["x"] = xc
            slot["y"] = yc

        idx += 1


def build_final_code_from_slots(slots):
    """
    슬롯 3개가 모두 채워져 있으면 "XYZ" 형태 문자열 리턴.
    하나라도 비어있으면 "NONE" 리턴.
    """
    digits = []

    i = 0
    while i < len(slots):
        s = slots[i]
        if s["char"] is None:
            return "NONE"
        digits.append(s["char"])
        i += 1

    # digits 를 이어붙이기
    code = ""
    i = 0
    while i < len(digits):
        code = code + digits[i]
        i += 1

    return code
