# utils/color_utils.py

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

