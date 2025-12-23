# utils/shared_mem_utils.py
# -*- coding: utf-8 -*-

import configparser
import time
import numpy as np
from multiprocessing import shared_memory

# --------------------------------------------------
# Config.ini 로드 (필요시 사용)
# --------------------------------------------------
CONFIG_INI_PATH = r"/home/kaisys/CheckWheelStatusPy/Config.ini"

_config = configparser.ConfigParser()
_config.read(CONFIG_INI_PATH)

# --------------------------------------------------
# 공유메모리 인덱스 (문서 기준)
# --------------------------------------------------
IDX_NEW_CAR_FLAG = 1
IDX_CAR_NO_0 = 2
IDX_CAR_NO_1 = 3
IDX_CAR_NO_2 = 4


# --------------------------------------------------
# 공유메모리 열기
# --------------------------------------------------
def open_or_create_shm(name, size):
    try:
        shm = shared_memory.SharedMemory(name=name, create=False)
        print("[SHM] attach:", name)
    except FileNotFoundError:
        shm = shared_memory.SharedMemory(name=name, size=size, create=True)
        print("[SHM] create:", name)

    arr = np.ndarray((size,), dtype=np.uint8, buffer=shm.buf)
    return shm, arr


# --------------------------------------------------
# 대차 번호 문자열을 3자리('0'~'9' or 'F')로 정규화
# --------------------------------------------------
def _normalize_car_no_3(final_code):
    s = str(final_code).strip()

    # NONE / 빈값이면 실패 처리
    if s == "" or s.upper() == "NONE":
        return "FFF"

    # 숫자만 추출
    digits = ""
    for ch in s:
        if ch.isdigit():
            digits += ch

    if digits == "":
        return "FFF"

    # 3자리 맞추기: 길면 앞 3자리, 짧으면 앞쪽을 F로 채움
    if len(digits) >= 3:
        return digits[:3]

    while len(digits) < 3:
        digits = "F" + digits

    return digits


# --------------------------------------------------
# 대차 번호 쓰기 (2~4 기록 후 flag(1)=1)
# 규칙: flag(1)==0일 때만 쓰기 가능
# --------------------------------------------------
def write_car_number(status_array,
                     final_code,
                     block=True,
                     timeout_sec=1.0,
                     poll_interval=0.02):
    """
    - status_array[1] == 0 (Done) 일 때만 2~4 쓰고 1=1(arrived)
    - block=True: timeout_sec 동안 0이 될 때까지 기다림
    - block=False: 바로 실패(False) 리턴
    """
    digits = _normalize_car_no_3(final_code)

    start_time = time.time()
    while True:
        if int(status_array[IDX_NEW_CAR_FLAG]) == 0:
            break

        if not block:
            return False

        if timeout_sec is not None:
            if (time.time() - start_time) > float(timeout_sec):
                return False

        time.sleep(poll_interval)

    # 2~4 ASCII 기록
    status_array[IDX_CAR_NO_0] = ord(digits[0])
    status_array[IDX_CAR_NO_1] = ord(digits[1])
    status_array[IDX_CAR_NO_2] = ord(digits[2])

    # 5~9 reserved = 0
    for i in range(5, 10):
        status_array[i] = 0

    # flag(1)=1 arrived
    status_array[IDX_NEW_CAR_FLAG] = 1

    print("[SHM] car_no write:", digits)
    return True


# --------------------------------------------------
# 휠상태 읽기 (기존 유지)
# --------------------------------------------------
def read_wheel_status_packet(status_array):
    """
    NOTE:
    - 이 함수는 'flag(10)==1' 기준으로 만든 기존 코드임.
    - 2nd는 flag(20)도 따로 봐야 프로토콜 완전 준수.
    """
    packet = {
        "car_no": "".join(chr(status_array[i]) for i in range(11, 14)),
        "stop_flag": int(status_array[0]),

        "wheel_1st_rotation": int(status_array[16]),
        "wheel_1st_position": int(status_array[17]),

        "wheel_2nd_rotation": int(status_array[26]),
        "wheel_2nd_position": int(status_array[27]),
    }
    return packet
