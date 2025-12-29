# utils/thresholds_utils.py
import json
import os
from config.config import THRESHOLDS_JSON, DEFAULT_THRESHOLDS


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
