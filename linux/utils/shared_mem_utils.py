# utils/shared_mem_utils.py
# -*- coding: utf-8 -*-

import configparser
import time
import numpy as np
from multiprocessing import shared_memory

# --------------------------------------------------
# Config.ini 로드
# --------------------------------------------------
CONFIG_INI_PATH = r"/home/kaisys/CheckWheelStatusPy/Config.ini"

_config = configparser.ConfigParser()
_config.read(CONFIG_INI_PATH)


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
# 대차 번호 쓰기 (2~4, flag=1)
# --------------------------------------------------
def write_car_number(status_array,
                     final_code,
                     block=True,
                     timeout_sec=None,
                     poll_interval=0.01):

    s = str(final_code).strip()

    if s == "" or s.upper() == "NONE":
        digits = "FFF"
    else:
        digits = ""
        for ch in s:
            if ch.isdigit():
                digits += ch
        if digits == "":
            digits = "FFF"
        if len(digits) >= 3:
            digits = digits[:3]
        else:
            while len(digits) < 3:
                digits = "F" + digits

    start_time = time.time()
    while True:
        if status_array[1] == 0:
            break
        if not block:
            return False
        if timeout_sec and time.time() - start_time > timeout_sec:
            return False
        time.sleep(poll_interval)

    status_array[2] = ord(digits[0])
    status_array[3] = ord(digits[1])
    status_array[4] = ord(digits[2])

    for i in range(5, 10):
        status_array[i] = 0

    status_array[1] = 1
    print("[SHM] car_no write:", digits)
    return True


# --------------------------------------------------
# 휠상태 읽기 (WS / DS 공통)
# --------------------------------------------------
def read_wheel_status_packet(status_array):
    """
    flag(10) == 1 일 때만 호출
    """
    packet = {
        "car_no": "".join(chr(status_array[i]) for i in range(11, 14)),
        "stop_flag": int(status_array[0]),

        # 1st wheel
        "wheel_1st_rotation": int(status_array[16]),
        "wheel_1st_position": int(status_array[17]),

        # 2nd wheel
        "wheel_2nd_rotation": int(status_array[26]),
        "wheel_2nd_position": int(status_array[27]),
    }
    return packet
