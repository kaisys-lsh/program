# test_sender_scenario.py
# --------------------------------------------------
# [테스트용] 5초 주기 정밀 시나리오 시뮬레이터
# - Detectron2 제거, SHM 제거
# - 5초마다 새로운 차량 생성
# - T=0: START
# - T=2: CAR_NO
# - T=3: 1st Wheel (WS, DS)
# - T=4: 2nd Wheel (WS, DS)
# --------------------------------------------------

import time
import zmq
import uuid
import random

# ==================================================
# 설정
# ==================================================
PUSH_BIND = "tcp://*:5888"

def _now_ms():
    return int(time.time() * 1000)

def _make_event_id():
    # car-{timestamp}-{uuid}
    return "car-{0}-{1}".format(_now_ms(), uuid.uuid4().hex[:6])

def _random_car_no():
    # 000 ~ 999 랜덤 문자열
    return "{:03d}".format(random.randint(0, 999))

def _random_flag():
    # 0 또는 1
    return random.choice([0, 1])

def main():
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PUSH)
    sock.bind(PUSH_BIND)
    
    print(f"[TEST] 5초 주기 시나리오 시작 ({PUSH_BIND})")
    print("-" * 40)

    try:
        while True:
            # =========================================
            # [T=0] START (차량 진입)
            # =========================================
            cycle_start = time.time()
            
            event_id = _make_event_id()
            target_car_no = _random_car_no() # 이번 사이클의 대차번호

            start_packet = {
                "type": "car_event",
                "event": "START",
                "car_no": None,
                "event_id": event_id,
                "ts_ms": _now_ms()
            }
            sock.send_json(start_packet)
            print(f"[0.0s] START  : ID={event_id} (Target No={target_car_no})")

            # 2초 대기
            time.sleep(2.0)

            # =========================================
            # [T=2] CAR_NO (번호 확정)
            # =========================================
            car_no_packet = {
                "type": "car_no",
                "event_id": event_id,
                "car_no": target_car_no,
                "ts_ms": _now_ms()
            }
            sock.send_json(car_no_packet)
            print(f"[2.0s] CAR_NO : {target_car_no}")

            # 1초 대기 (START 기준 3초 경과)
            time.sleep(1.0)

            # =========================================
            # [T=3] 1st Wheel Status (WS, DS)
            # =========================================
            # WS 1st
            ws_1st = {
                "type": "wheel_status",
                "pos": "WS",
                "car_no": target_car_no,
                "stop_flag": 0,
                "wheel1_rotation": _random_flag(),
                "wheel1_position": _random_flag(),
                "wheel2_rotation": 0, # 1st니까 2nd는 0
                "wheel2_position": 0,
                "src": "1st",
                "ts_ms": _now_ms(),
                "event_id": event_id
            }
            sock.send_json(ws_1st)

            # DS 1st
            ds_1st = {
                "type": "wheel_status",
                "pos": "DS",
                "car_no": target_car_no,
                "stop_flag": 0,
                "wheel1_rotation": _random_flag(),
                "wheel1_position": _random_flag(),
                "wheel2_rotation": 0,
                "wheel2_position": 0,
                "src": "1st",
                "ts_ms": _now_ms(),
                "event_id": event_id
            }
            sock.send_json(ds_1st)
            
            print(f"[3.0s] WHEEL  : 1st Data Sent (WS/DS) -> No={target_car_no}")

            # 1초 대기 (START 기준 4초 경과)
            time.sleep(1.0)

            # =========================================
            # [T=4] 2nd Wheel Status (WS, DS)
            # =========================================
            # WS 2nd
            ws_2nd = {
                "type": "wheel_status",
                "pos": "WS",
                "car_no": target_car_no,
                "stop_flag": 0,
                "wheel1_rotation": 0, # 2nd니까 1st는 0
                "wheel1_position": 0,
                "wheel2_rotation": _random_flag(),
                "wheel2_position": _random_flag(),
                "src": "2nd",
                "ts_ms": _now_ms(),
                "event_id": event_id
            }
            sock.send_json(ws_2nd)

            # DS 2nd
            ds_2nd = {
                "type": "wheel_status",
                "pos": "DS",
                "car_no": target_car_no,
                "stop_flag": 0,
                "wheel1_rotation": 0,
                "wheel1_position": 0,
                "wheel2_rotation": _random_flag(),
                "wheel2_position": _random_flag(),
                "src": "2nd",
                "ts_ms": _now_ms(),
                "event_id": event_id
            }
            sock.send_json(ds_2nd)
            
            print(f"[4.0s] WHEEL  : 2nd Data Sent (WS/DS) -> No={target_car_no}")

            # 1초 대기 (START 기준 5초 경과 -> 다음 사이클)
            remain = 5.0 - (time.time() - cycle_start)
            if remain > 0:
                time.sleep(remain)
            
            print("-" * 40)

    except KeyboardInterrupt:
        print("\n[TEST] 종료합니다.")
    finally:
        sock.close()
        ctx.term()

if __name__ == "__main__":
    main()