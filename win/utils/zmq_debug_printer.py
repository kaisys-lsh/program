# utils/zmq_debug_printer.py
# ZMQ로 들어오는 JSON 데이터를 사람이 보기 좋게 출력하는 디버그용 유틸

import json
from datetime import datetime


def _print_one_json(data: dict):
    msg_type = data.get("type", "알수없음")
    print("▶ 메시지 타입:", msg_type)

    # -----------------------------
    # car_event
    # -----------------------------
    if msg_type == "car_event":
        print("  [대차 이벤트]")
        print("   - 이벤트:", data.get("event"))
        print("   - 대차번호:", data.get("car_no"))
        print("   - event_id:", data.get("event_id"))

    # -----------------------------
    # wheel_event (flat)
    # -----------------------------
    elif msg_type == "wheel_event":
        print("  [휠 상태 이벤트]")
        print("   - 위치(WS/DS):", data.get("pos"))
        print("   - 대차번호:", data.get("wheel_car_no") or data.get("car_no"))
        print("   - event_id:", data.get("event_id"))

        print(
            "   - 앞바퀴 회전:", data.get("wheel_1st_rotation"),
            "/ 위치:", data.get("wheel_1st_position")
        )
        print(
            "   - 뒷바퀴 회전:", data.get("wheel_2nd_rotation"),
            "/ 위치:", data.get("wheel_2nd_position")
        )

    # -----------------------------
    # car_update (nested)
    # -----------------------------
    elif msg_type == "car_update":
        print("  [대차 업데이트]")
        print("   - 위치(WS/DS):", data.get("pos"))
        print("   - 대차번호:", data.get("car_no"))
        print("   - event_id:", data.get("event_id"))

        wheel = data.get("wheel", {})
        if wheel is None or not isinstance(wheel, dict):
            wheel = {}

        print(
            "   - 앞바퀴 회전:", wheel.get("wheel_1st_rotation"),
            "/ 위치:", wheel.get("wheel_1st_position")
        )
        print(
            "   - 뒷바퀴 회전:", wheel.get("wheel_2nd_rotation"),
            "/ 위치:", wheel.get("wheel_2nd_position")
        )

    # -----------------------------
    # 기타
    # -----------------------------
    else:
        print("  [알 수 없는 메시지 구조]")
        for k, v in data.items():
            print(f"   - {k}: {v}")


def print_zmq_debug(raw_text: str):
    """
    ZMQ 수신 raw text(JSON 문자열)를 사람이 보기 좋은 한글 로그로 출력
    - 여러 JSON이 줄바꿈으로 붙어 들어오는 케이스 지원
    """
    print("\n" + "=" * 80)
    print("[ZMQ 수신 디버그] 수신 시각:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    if not isinstance(raw_text, str):
        print("❌ 문자열 아님")
        print(raw_text)
        print("=" * 80)
        return

    s = raw_text.strip()
    if not s:
        print("❌ 빈 문자열")
        print("=" * 80)
        return

    # 여러 줄로 붙어온 메시지 방어
    lines = []
    if "\n" in s:
        for ln in s.splitlines():
            ln = ln.strip()
            if ln:
                lines.append(ln)
    else:
        lines = [s]

    parsed_any = False
    for one in lines:
        try:
            data = json.loads(one)
        except Exception:
            print("❌ JSON 파싱 실패")
            print("원본:", one)
            continue

        if not isinstance(data, dict):
            print("❌ JSON은 맞지만 dict 아님:", type(data))
            print("값:", data)
            continue

        parsed_any = True
        _print_one_json(data)

    if not parsed_any:
        print("❌ 유효한 JSON 메시지 없음")

    print("=" * 80)
