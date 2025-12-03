import json
from config import THRESHOLDS_JSON, DEFAULT_THRESHOLDS

def load_thresholds_from_json():
    try:
        with open(THRESHOLDS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)

        out = DEFAULT_THRESHOLDS.copy()
        for key in out.keys():
            if key in data:
                out[key] = float(data[key])

        # weak ≤ mid ≤ strong 정렬 보장
        w, m, s = sorted([out["weak"], out["mid"], out["strong"]])
        out["weak"], out["mid"], out["strong"] = w, m, s
        return out
    except Exception:
        return DEFAULT_THRESHOLDS.copy()

def save_thresholds_to_json(thresholds_dict):
    try:
        tmp = THRESHOLDS_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(thresholds_dict, f, ensure_ascii=False, indent=2)
        # 원자적 교체
        import os
        os.replace(tmp, THRESHOLDS_JSON)
    except Exception as e:
        print("[WARN] thresholds.json 저장 실패:", e)
