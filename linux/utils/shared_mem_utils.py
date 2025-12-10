# utils/shared_mem_utils.py
# -*- coding: utf-8 -*-
#
# 공유메모리(SM_NAME, SM_SIZE)를 열고,
# 대차 번호를 [1] ~ [4] 인덱스 규칙대로 기록하는 유틸.
# WS / DS 두 종류를 Config.ini 기반으로 선택 가능하게 만든다.

import configparser
import time
import numpy as np
from multiprocessing import shared_memory


# --------------------------------------------------
# 0) Config.ini 로드
#    - [SYSTEM], [WS_POS], [DS_POS] 사용
# --------------------------------------------------
CONFIG_INI_PATH = r"/home/kaisys/CheckWheelStatusPy/Config.ini"
SEC_SYSTEM = "SYSTEM"

_config = configparser.ConfigParser()
_config.read(CONFIG_INI_PATH)


# --------------------------------------------------
# 1) 섹션 이름(WS_POS / DS_POS)에 따라
#    SM_Name / SM_Size를 읽어서 공유메모리 열기
# --------------------------------------------------
def get_shared_memory(pos_section="WS_POS"):
    """
    pos_section:
      - "WS_POS" or "DS_POS" (Config.ini 섹션 이름)
    
    반환:
      - shm          : SharedMemory 객체
      - status_array : np.ndarray(shape=(SM_SIZE,), dtype=uint8)

    예:
      shm_ws, arr_ws = get_shared_memory("WS_POS")
      shm_ds, arr_ds = get_shared_memory("DS_POS")
    """
    if not _config.has_section(pos_section):
        raise ValueError(f"[SHM] Config.ini에 섹션 없음: {pos_section}")

    sm_name = _config.get(pos_section, "SM_Name")
    sm_size = _config.getint(pos_section, "SM_Size")

    try:
        shm = shared_memory.SharedMemory(name=sm_name, create=False)
        print(f"[SHM] 기존 공유메모리 참조 성공: {sm_name}, size = {sm_size}")
    except FileNotFoundError:
        shm = shared_memory.SharedMemory(name=sm_name, size=sm_size, create=True)
        print(f"[SHM] 공유메모리 새로 생성: {sm_name}, size = {sm_size}")

    status_array = np.ndarray((sm_size,), dtype=np.uint8, buffer=shm.buf)
    return shm, status_array



def open_or_create_shm(name, size):
    """
    name, size 를 받아서 SharedMemory를 열거나(create) 생성.
    np.uint8 1차원 배열 view도 같이 리턴한다.

    return: (shm_obj, status_array)
    """
    try:
        shm = shared_memory.SharedMemory(name=name, create=False)
        print("[SHM] 기존 공유메모리 참조:", name)
    except FileNotFoundError:
        shm = shared_memory.SharedMemory(name=name, create=True, size=size)
        print("[SHM] 공유메모리 새로 생성:", name)

    status_array = np.ndarray((size,), dtype=np.uint8, buffer=shm.buf)
    return shm, status_array


# --------------------------------------------------
# 2) 대차 번호 쓰기
#    - txt에서 정의한 [대차번호 작성방법] 구현
# --------------------------------------------------
def write_car_number(status_array,
                     final_code,
                     block=True,
                     timeout_sec=None,
                     poll_interval=0.01):
    """
    공유메모리에 대차 번호 3자리를 기록한다.

    [규칙 요약]
    - 인덱스 1:
        0일 때만 새 번호를 쓸 수 있음.
        번호를 다 쓴 뒤 1로 바꿔서 "새 번호 도착" 알림.
    - 인덱스 2,3,4:
        대차 번호 ASCII ('0'~'9' / 실패 시 'F')
    - 인덱스 5~9:
        Reserved → 0으로 채움.

    파라미터:
      - status_array : get_shared_memory()에서 얻은 numpy 배열
      - final_code   : "123", "045", "NONE" 등 문자열
      - block        : True면 flag가 0이 될 때까지 대기
      - timeout_sec  : block=True일 때 최대 대기 시간 (None이면 무한대기)
      - poll_interval: flag가 0인지 주기적으로 확인하는 간격(sec)

    반환:
      - True : 기록 성공
      - False: flag가 끝까지 0이 되지 않아 기록 실패
    """
    # 1) final_code를 길이 3짜리 문자열로 정리
    s = str(final_code).strip()

    # 인식 실패 또는 비어있는 값이면 "FFF"
    if s == "" or s.upper() == "NONE":
        digits = "FFF"
    else:
        # 숫자만 추출
        digits = ""
        i = 0
        while i < len(s):
            ch = s[i]
            if ch.isdigit():
                digits = digits + ch
            i = i + 1

        # 숫자가 하나도 없으면 "FFF"
        if digits == "":
            digits = "FFF"

        # 길이 보정: 3자리로 맞추기
        if len(digits) >= 3:
            digits = digits[:3]
        else:
            # 앞을 'F'로 채워서 3자리 맞춤 (예: "5" → "FF5")
            while len(digits) < 3:
                digits = "F" + digits

    # 2) 인덱스 1(flag)이 0이 될 때까지 대기
    start_time = time.time()

    while True:
        flag = status_array[1]
        if flag == 0:
            break

        if not block:
            # 넌블록 모드면 즉시 실패 반환
            print("[SHM] 번호 기록 실패: flag!=0 (논블록 모드)")
            return False

        if timeout_sec is not None:
            now = time.time()
            if now - start_time > timeout_sec:
                print("[SHM] 번호 기록 실패: flag!=0 (타임아웃)")
                return False

        time.sleep(poll_interval)

    # 3) 실제 번호 쓰기 (2~4번 인덱스)
    status_array[2] = ord(digits[0])
    status_array[3] = ord(digits[1])
    status_array[4] = ord(digits[2])

    # 4) Reserved 영역(5~9)은 0으로 채운다.
    idx = 5
    while idx <= 9:
        status_array[idx] = 0
        idx = idx + 1

    # 5) 마지막에 flag = 1 (새 번호 도착)
    status_array[1] = 1

    print("[SHM] 대차 번호 기록 완료 →", digits)
    return True
