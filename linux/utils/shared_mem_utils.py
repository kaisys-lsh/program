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
IDX_STOP_FLAG = 0  # 0: 이동 / 1: 정지

# --- Car No ---
IDX_NEW_CAR_FLAG = 1  # 0: Done / 1: arrived
IDX_CAR_NO_0 = 2
IDX_CAR_NO_1 = 3
IDX_CAR_NO_2 = 4

# --- DS Wheel ---
DS_FLAG_1 = 10
DS_CAR_1 = (11, 12, 13)
DS_ROT_1 = 16
DS_POS_1 = 17

DS_FLAG_2 = 20
DS_CAR_2 = (21, 22, 23)
DS_ROT_2 = 26
DS_POS_2 = 27

# --- WS Wheel ---
WS_FLAG_1 = 30
WS_CAR_1 = (31, 32, 33)
WS_ROT_1 = 36
WS_POS_1 = 37

WS_FLAG_2 = 40
WS_CAR_2 = (41, 42, 43)
WS_ROT_2 = 46
WS_POS_2 = 47


# --------------------------------------------------
# 공유메모리 열기
# --------------------------------------------------
def open_or_create_shm(name, size):
    try:
        shm = shared_memory.SharedMemory(name=name, create=False)
        real_size = shm.size  # ✅ 실제 크기 사용
        print("[SHM] attach:", name, "size=", real_size)
    except FileNotFoundError:
        shm = shared_memory.SharedMemory(name=name, size=size, create=True)
        real_size = shm.size
        print("[SHM] create:", name, "size=", real_size)

    arr = np.ndarray((real_size,), dtype=np.uint8, buffer=shm.buf)
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
def write_car_number(
    status_array,
    final_code,
    block=True,
    timeout_sec=1.0,
    poll_interval=0.02
):
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

    #print("[SHM] car_no write:", digits)
    return True


# --------------------------------------------------
# 휠상태 읽기 유틸 (문서 구조 준수)
# - flag==1이면 읽고, clear_flag=True면 flag=0으로 내림
# --------------------------------------------------
def _read_ascii3(arr, idxs):
    return "".join(chr(int(arr[i])) for i in idxs)


def read_wheel_once(status_array, pos_name, wheel_no, clear_flag=True):
    """
    pos_name: "DS" or "WS"
    wheel_no: 1 (1st) or 2 (2nd)

    return:
      - flag==1이면 packet(dict) 반환
      - flag==0이면 None
    """
    if pos_name == "DS":
        if wheel_no == 1:
            flag_i = DS_FLAG_1
            car_i = DS_CAR_1
            rot_i = DS_ROT_1
            pos_i = DS_POS_1
        else:
            flag_i = DS_FLAG_2
            car_i = DS_CAR_2
            rot_i = DS_ROT_2
            pos_i = DS_POS_2
    else:  # "WS"
        if wheel_no == 1:
            flag_i = WS_FLAG_1
            car_i = WS_CAR_1
            rot_i = WS_ROT_1
            pos_i = WS_POS_1
        else:
            flag_i = WS_FLAG_2
            car_i = WS_CAR_2
            rot_i = WS_ROT_2
            pos_i = WS_POS_2

    if int(status_array[flag_i]) != 1:
        return None

    packet = {
        "car_no": _read_ascii3(status_array, car_i),
        "stop_flag": int(status_array[IDX_STOP_FLAG]),
        "rotation": int(status_array[rot_i]),
        "position": int(status_array[pos_i]),
        "pos_name": pos_name,
        "wheel_no": wheel_no,
    }

    if clear_flag:
        status_array[flag_i] = 0

    return packet


def read_wheel_pair(status_array, pos_name, clear_flag=True):
    """
    1st/2nd 둘 다 읽어서 반환(없으면 None)
    return: (p1, p2)
      - p1: wheel_no=1 packet or None
      - p2: wheel_no=2 packet or None
    """
    p1 = read_wheel_once(status_array, pos_name, 1, clear_flag=clear_flag)
    p2 = read_wheel_once(status_array, pos_name, 2, clear_flag=clear_flag)
    return p1, p2
