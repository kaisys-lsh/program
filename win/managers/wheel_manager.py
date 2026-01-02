# win/managers/wheel_manager.py
# -*- coding: utf-8 -*-
from PyQt5.QtCore import QObject, pyqtSignal

# ==================================================
# 1. 순수 로직 함수들 (Static Utils)
#    - 다른 모듈(DbPoller 등)에서도 import해서 쓸 수 있게 함
# ==================================================

def judge_one_wheel(rot, pos=None):
    """
    센서값(Rotation, Position) -> 상태 문자열 변환
    입력: (rot, pos) 튜플 or dict or 개별 인자
    리턴: "정상" / "비정상" / "검출X"
    """
    try:
        # dict 입력 ({ "rotation": 1, "position": 1 })
        if pos is None and isinstance(rot, dict):
            r = int(rot.get("rotation", 0))
            p = int(rot.get("position", 0))
        # 튜플/리스트 ([1, 1])
        elif pos is None and isinstance(rot, (tuple, list)) and len(rot) >= 2:
            r = int(rot[0])
            p = int(rot[1])
        # 개별 입력 (1, 1)
        else:
            r = int(rot)
            p = int(pos)
    except Exception:
        return "검출X"

    if r == 2 or p == 2:
        return "비정상"
    if r == 0 or p == 0:
        return "검출X"
    return "정상"


def combine_wheel_status(ws_w1, ws_w2, ds_w1, ds_w2):
    """
    4개 휠 상태를 종합하여 하나의 상태로 요약
    우선순위: 비정상 > 검출X > 정상
    """
    src = [ws_w1, ws_w2, ds_w1, ds_w2]
    statuses = [str(s).strip() for s in src if s is not None and str(s).strip()]

    if not statuses:
        return ""

    if "비정상" in statuses:
        return "비정상"
    
    # "검출X" 또는 "인식 실패" 등이 있으면
    for s in statuses:
        if s in ("검출X", "인식 실패", "NO_DATA"):
            return "검출X"

    return "정상"


def get_wheel_status_color(status_text):
    """
    상태 문자열에 따른 UI 표시 색상 리턴
    """
    s = str(status_text).strip()
    if s == "비정상":
        return "#FF0000"  # 빨강
    if s in ("검출X", "인식 실패", "NO_DATA"):
        return "#FFFF00"  # 노랑
    if s == "정상":
        return "#00FF00"  # 초록
    return "#FFFFFF"      # 흰색 (데이터 없음)


# ==================================================
# 2. 휠 상태 매니저 (데이터 처리 및 신호 발송)
# ==================================================
class WheelStatusManager(QObject):
    """
    ZMQ 등에서 받은 휠 데이터를 처리하고
    1) DB Writer에 저장 요청 (Patch)
    2) UI Manager에 실시간 업데이트 요청 (Signal)
    """
    # UI 실시간 업데이트용 신호: (pos="WS"|"DS", status1, status2)
    sig_wheel_ui_update = pyqtSignal(str, str, str)

    def __init__(self, db_writer):
        super().__init__()
        self.db_writer = db_writer

    def process_incoming_data(self, data: dict, current_event_id: str):
        """
        ZMQ에서 수신한 JSON 데이터를 분석하여 처리
        """
        pos = str(data.get("pos", "")).strip().upper()  # WS / DS
        event_id = str(data.get("event_id", "") or "").strip()

        if not pos:
            return

        # 1) 데이터 파싱 및 판정
        # (호환성: wheel 객체 안에 있을 수도 있고, 평문에 있을 수도 있음)
        wheel_obj = data.get("wheel", {})
        if wheel_obj:
            w1 = (wheel_obj.get("wheel_1st_rotation", 0), wheel_obj.get("wheel_1st_position", 0))
            w2 = (wheel_obj.get("wheel_2nd_rotation", 0), wheel_obj.get("wheel_2nd_position", 0))
        else:
            w1 = (data.get("wheel_1st_rotation", 0), data.get("wheel_1st_position", 0))
            w2 = (data.get("wheel_2nd_rotation", 0), data.get("wheel_2nd_position", 0))

        status1 = judge_one_wheel(w1)
        status2 = judge_one_wheel(w2)

        # 2) DB 저장 (event_id가 있을 때만)
        if event_id:
            patch = {"event_id": event_id}
            if pos == "WS":
                patch.update({
                    "ws_wheel1_status": status1,
                    "ws_wheel2_status": status2,
                    "wheel_ws_done": 1
                })
            elif pos == "DS":
                patch.update({
                    "ds_wheel1_status": status1,
                    "ds_wheel2_status": status2,
                    "wheel_ds_done": 1
                })
            
            self.db_writer.enqueue(patch)

        # 3) UI 업데이트 신호 발송
        # (현재 모니터링 중인 차량인 경우에만 화면 갱신)
        if current_event_id and event_id == current_event_id:
            self.sig_wheel_ui_update.emit(pos, status1, status2)