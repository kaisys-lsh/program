# utils/color_json_utils.py
# --------------------------------------------------
# thresholds_utils.py + color_utils.py (통합본)
# - thresholds.json 로드/저장 + 정규화
# - dB 값/휠 상태에 따른 색상 리턴
# --------------------------------------------------

import json
import os

from config.config import THRESHOLDS_JSON, DEFAULT_THRESHOLDS


# ==================================================
# Thresholds (load/save/normalize)
# ==================================================
def _normalize_thresholds(d: dict):
    """
    weak/mid/strong/min 값을 float로 정리 + weak≤mid≤strong 보장
    """
    base = {}
    try:
        base = dict(DEFAULT_THRESHOLDS)
    except Exception:
        base = {"weak": 3.0, "mid": 4.0, "strong": 5.0, "min": 0.0}

    out = base.copy()

    if isinstance(d, dict):
        for k in out.keys():
            if k in d:
                try:
                    out[k] = float(d[k])
                except Exception:
                    pass

    # weak ≤ mid ≤ strong 정렬 보장
    try:
        w, m, s = sorted([out["weak"], out["mid"], out["strong"]])
        out["weak"], out["mid"], out["strong"] = w, m, s
    except Exception:
        pass

    return out


def load_thresholds_from_json():
    try:
        with open(THRESHOLDS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _normalize_thresholds(data)
    except Exception:
        return _normalize_thresholds({})


def save_thresholds_to_json(thresholds_dict):
    try:
        norm = _normalize_thresholds(thresholds_dict)

        tmp = THRESHOLDS_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(norm, f, ensure_ascii=False, indent=2)

        # 원자적 교체
        os.replace(tmp, THRESHOLDS_JSON)
    except Exception as e:
        print("[WARN] thresholds.json 저장 실패:", e)


# ==================================================
# Color (dB / wheel status)
# ==================================================
def color_for_db(thresholds, db_value):
    if db_value is None:
        return "#FFFFFF"

    try:
        v = float(db_value)
    except Exception:
        v = 0.0

    weak = float(thresholds.get("weak", 3.0))
    mid = float(thresholds.get("mid", 4.0))
    strong = float(thresholds.get("strong", 5.0))

    if v < weak:
        return "#67E467"
    if v < mid:
        return "#4A89E9"
    if v < strong:
        return "#E7E55F"
    return "#EB5E5E"


def wheel_color_for_status(status_text):
    if status_text == "비정상":
        return "#EB5E5E"
    if status_text == "검출X" or status_text == "인식 실패":
        return "#E7E55F"
    return "#FFFFFF"
