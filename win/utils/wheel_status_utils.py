# utils/wheel_status_utils.py

def judge_one_wheel(rot, pos):
    """
    rot: 0/1/2, pos: 0/1/2
    return: "정상" / "비정상" / "검출X"
    규칙:
      - rot==2 또는 pos==2  => 비정상
      - rot==0 또는 pos==0  => 검출X
      - 그 외(1,1)          => 정상
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
    """
    4개 상태를 종합해서 overall 한 단어로 요약.
    우선순위: 비정상 > 검출X(또는 인식 실패) > 정상
    """
    src = [ws_w1, ws_w2, ds_w1, ds_w2]

    statuses = []
    for s in src:
        if s is None:
            continue
        ss = str(s).strip()
        if not ss:
            continue
        statuses.append(ss)

    if not statuses:
        return ""

    # 1) 하나라도 비정상이면 비정상
    for s in statuses:
        if s == "비정상":
            return "비정상"

    # 2) 하나라도 검출X/인식 실패면 검출X
    for s in statuses:
        if s in ("검출X", "인식 실패"):
            return "검출X"

    # 3) 정상 하나라도 있으면 정상
    for s in statuses:
        if s == "정상":
            return "정상"

    return ""
