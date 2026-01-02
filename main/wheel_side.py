# wheel_side.py
# -*- coding: utf-8 -*-

import time
from shm_100 import Shm100

SHM_NAME = "POSCO_SHM_100"

def main():
    shm = Shm100(SHM_NAME, create=False)
    print("[WHEEL] start")

    try:
        while True:
            # 1) 대차번호 수신
            car = shm.read_car_no(clear=True)
            if car is not None:
                print("[WHEEL] recv car =", car)

                # 2) (예시) 정지상태 업데이트
                shm.set_stop(1)     # 정지
                # shm.set_stop(0)   # 이동

                # 3) (예시) DS/WS 결과 쓰기
                # rot: 1(회전) / 2(무회전) / 0(실패)
                # pos: 1(정상) / 2(비정상) / 0(실패)
                shm.write_ds1(car, rot=1, pos=1, block=True, timeout=1.0)
                shm.write_ds2(car, rot=2, pos=1, block=True, timeout=1.0)
                shm.write_ws1(car, rot=1, pos=2, block=True, timeout=1.0)
                shm.write_ws2(car, rot=1, pos=1, block=True, timeout=1.0)

            # 4) (선택) HMI 같은 소비자가 휠 결과를 읽는 경우라면 아래처럼 read_* 사용
            # ds1 = shm.read_ds1()
            # if ds1: print("[WHEEL] ds1 readback", ds1)

            time.sleep(0.01)

    finally:
        shm.close()

if __name__ == "__main__":
    main()
