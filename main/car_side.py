# car_side.py
# -*- coding: utf-8 -*-

import time
from shm_100 import Shm100

SHM_NAME = "POSCO_SHM_100"

def main():
    shm = Shm100(SHM_NAME, create=True)  # 최초 1번만 create=True로 띄우면 됨
    print("[CAR] start")

    no = 100
    try:
        while True:
            # (선택) 휠쪽이 써준 정지상태 확인
            stop = shm.get_stop()
            # print("[CAR] stop =", stop)

            # 예시: 0.5초마다 번호 하나 쏘기
            s = f"{no % 1000:03d}"
            ok = shm.write_car_no(s, block=True, timeout=1.0)
            print("[CAR] send", s, "ok=", ok)

            no += 1
            time.sleep(0.5)

    finally:
        shm.close()
        # 운영에서는 unlink 하지마(다른 프로세스 붙어있으면 깨짐)
        # shm.unlink()

if __name__ == "__main__":
    main()
