# utils/wheel_status_utils.py

def judge_one_wheel(rot, pos):
    """
    rot: 0/1/2, pos: 0/1/2
    return: "정상" / "비정상" / "검출X"
    """
    try:
        r = int(rot)
        p = int(pos)
    except Exception:
        return "검출X"

    if r == 2 or p == 2:
        return "비정상"
    if r == 0 or p == 0:
        return "검출X"
    return "정상"


def combine_overall_wheel_status(ws_w1, ws_w2, ds_w1, ds_w2):
    statuses = []
    for s in [ws_w1, ws_w2, ds_w1, ds_w2]:
        if s:
            statuses.append(s)

    if not statuses:
        return ""

    for s in statuses:
        if s == "비정상":
            return "비정상"

    for s in statuses:
        if s in ("검출X", "인식 실패"):
            return "검출X"

    for s in statuses:
        if s == "정상":
            return "정상"

    return ""
