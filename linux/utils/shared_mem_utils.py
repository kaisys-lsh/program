# utils/shared_mem_utils.py
# -*- coding: utf-8 -*-

import time
import numpy as np
from multiprocessing import shared_memory

from config import config


# ---------------------------
# SHM open/create
# ---------------------------
def open_or_create_shm(name, size):
    try:
        shm = shared_memory.SharedMemory(name=name, create=False)
        real_size = shm.size
        print("[SHM] attach:", name, "size=", real_size)
    except FileNotFoundError:
        shm = shared_memory.SharedMemory(name=name, size=size, create=True)
        real_size = shm.size
        print("[SHM] create:", name, "size=", real_size)

    arr = np.ndarray((real_size,), dtype=np.uint8, buffer=shm.buf)
    return shm, arr


# ---------------------------
# car_no normalize (간단 버전)
# - (권장) 최종 정규화는 digit_utils에서 끝내고,
#   여기서는 안전하게 "없으면 FFF" 정도만 처리
# ---------------------------
def _safe_carno3(s):
    if s is None:
        return "FFF"
    t = str(s).strip()
    if t == "" or t.upper() == "NONE":
        return "FFF"

    digits = ""
    for ch in t:
        if ch.isdigit():
            digits += ch

    if len(digits) >= 3:
        return digits[:3]

    while len(digits) < 3:
        digits = "F" + digits
    return digits


def write_car_number(status_array, final_code, block=True, timeout_sec=1.0, poll_interval=0.02):
    digits = _safe_carno3(final_code)

    start_time = time.time()
    while True:
        if int(status_array[config.IDX_NEW_CAR_FLAG]) == 0:
            break

        if not block:
            return False

        if timeout_sec is not None:
            if (time.time() - start_time) > float(timeout_sec):
                return False

        time.sleep(poll_interval)

    status_array[config.IDX_CAR_NO_0] = ord(digits[0])
    status_array[config.IDX_CAR_NO_1] = ord(digits[1])
    status_array[config.IDX_CAR_NO_2] = ord(digits[2])

    i = 5
    while i < 10:
        status_array[i] = 0
        i += 1

    status_array[config.IDX_NEW_CAR_FLAG] = 1
    return True


# ---------------------------
# wheel read (디버그/테스트 전용)
# ⚠ 메인에서 WheelFlagWatcher를 쓰는 경우,
#    아래 함수들을 동시에 쓰면 flag를 먼저 내려서
#    "휠상태가 안 들어오는 것처럼" 보일 수 있음.
# ---------------------------
def _read_ascii3_safe(arr, idxs):
    s = ""
    i = 0
    while i < 3:
        v = int(arr[idxs[i]])
        ch = "F"
        try:
            c = chr(v)
            if c.isdigit():
                ch = c
        except Exception:
            ch = "F"
        s += ch
        i += 1
    return s


def read_wheel_once(status_array, pos_name, wheel_no, clear_flag=True):
    pos = str(pos_name).upper().strip()

    if pos == "DS":
        if wheel_no == 1:
            flag_i, car_i, rot_i, pos_i = config.DS_FLAG_1, config.DS_CAR_1, config.DS_ROT_1, config.DS_POS_1
        else:
            flag_i, car_i, rot_i, pos_i = config.DS_FLAG_2, config.DS_CAR_2, config.DS_ROT_2, config.DS_POS_2
    else:
        if wheel_no == 1:
            flag_i, car_i, rot_i, pos_i = config.WS_FLAG_1, config.WS_CAR_1, config.WS_ROT_1, config.WS_POS_1
        else:
            flag_i, car_i, rot_i, pos_i = config.WS_FLAG_2, config.WS_CAR_2, config.WS_ROT_2, config.WS_POS_2

    if int(status_array[flag_i]) != 1:
        return None

    packet = {
        "car_no": _read_ascii3_safe(status_array, car_i),
        "stop_flag": int(status_array[config.IDX_STOP_FLAG]),
        "rotation": int(status_array[rot_i]),
        "position": int(status_array[pos_i]),
        "pos_name": pos,
        "wheel_no": int(wheel_no),
    }

    if clear_flag:
        status_array[flag_i] = 0

    return packet


def read_wheel_pair(status_array, pos_name, clear_flag=True):
    p1 = read_wheel_once(status_array, pos_name, 1, clear_flag=clear_flag)
    p2 = read_wheel_once(status_array, pos_name, 2, clear_flag=clear_flag)
    return p1, p2
