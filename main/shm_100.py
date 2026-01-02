# shm_100.py
# -*- coding: utf-8 -*-

import time
from multiprocessing import shared_memory


SIZE = 100

# ---- offsets ----
IDX_STOP = 0

IDX_CAR_FLAG = 1
IDX_CAR0 = 2  # ASCII
IDX_CAR1 = 3
IDX_CAR2 = 4

# DS 1st
IDX_DS1_FLAG = 10
IDX_DS1_CAR = 11  # 11,12,13
IDX_DS1_ROT = 16
IDX_DS1_POS = 17

# DS 2nd
IDX_DS2_FLAG = 20
IDX_DS2_CAR = 21
IDX_DS2_ROT = 26
IDX_DS2_POS = 27

# WS 1st
IDX_WS1_FLAG = 30
IDX_WS1_CAR = 31
IDX_WS1_ROT = 36
IDX_WS1_POS = 37

# WS 2nd
IDX_WS2_FLAG = 40
IDX_WS2_CAR = 41
IDX_WS2_ROT = 46
IDX_WS2_POS = 47


def _now():
    return time.time()


def _to3(s):
    s = str(s)
    if len(s) >= 3:
        s = s[:3]
    else:
        s = s.zfill(3)
    out = []
    for ch in s:
        if ch.isdigit():
            out.append(ch)
        else:
            out.append("F")
    return "".join(out)


class Shm100:
    def __init__(self, name, create=False):
        self.name = str(name)
        if create:
            self.shm = shared_memory.SharedMemory(name=self.name, create=True, size=SIZE)
            self.buf = self.shm.buf
            for i in range(SIZE):
                self.buf[i] = 0
        else:
            self.shm = shared_memory.SharedMemory(name=self.name, create=False)
            self.buf = self.shm.buf

    def close(self):
        self.shm.close()

    def unlink(self):
        self.shm.unlink()

    # -------------------------
    # generic flag helpers
    # -------------------------
    def wait_flag(self, idx_flag, want, timeout=None, sleep=0.001):
        t0 = _now()
        while True:
            if int(self.buf[idx_flag]) == int(want):
                return True
            if timeout is not None and (_now() - t0) > float(timeout):
                return False
            time.sleep(sleep)

    # -------------------------
    # STOP (0)
    # -------------------------
    def set_stop(self, stop):
        self.buf[IDX_STOP] = 1 if stop else 0

    def get_stop(self):
        return int(self.buf[IDX_STOP])

    # -------------------------
    # CAR NO (1~4)
    # producer: car detect
    # consumer: wheel status
    # -------------------------
    def write_car_no(self, car_no, block=True, timeout=0.2):
        if block:
            ok = self.wait_flag(IDX_CAR_FLAG, 0, timeout=timeout)
            if not ok:
                return False
        else:
            if int(self.buf[IDX_CAR_FLAG]) != 0:
                return False

        s = _to3(car_no)
        self.buf[IDX_CAR0] = ord(s[0])
        self.buf[IDX_CAR1] = ord(s[1])
        self.buf[IDX_CAR2] = ord(s[2])
        self.buf[IDX_CAR_FLAG] = 1
        return True

    def read_car_no(self, clear=True):
        if int(self.buf[IDX_CAR_FLAG]) != 1:
            return None
        s = "".join([chr(self.buf[IDX_CAR0]), chr(self.buf[IDX_CAR1]), chr(self.buf[IDX_CAR2])])
        if clear:
            self.buf[IDX_CAR_FLAG] = 0
        return s

    # -------------------------
    # Wheel blocks (DS/WS 1st/2nd)
    # rotation: 0/1/2, pos: 0/1/2
    # -------------------------
    def _write_wheel(self, idx_flag, idx_car, idx_rot, idx_pos, car_no, rot, pos, block=True, timeout=0.2):
        if block:
            ok = self.wait_flag(idx_flag, 0, timeout=timeout)
            if not ok:
                return False
        else:
            if int(self.buf[idx_flag]) != 0:
                return False

        s = _to3(car_no)
        self.buf[idx_car + 0] = ord(s[0])
        self.buf[idx_car + 1] = ord(s[1])
        self.buf[idx_car + 2] = ord(s[2])

        self.buf[idx_rot] = int(rot) & 0xFF
        self.buf[idx_pos] = int(pos) & 0xFF

        self.buf[idx_flag] = 1
        return True

    def _read_wheel(self, idx_flag, idx_car, idx_rot, idx_pos, clear=True):
        if int(self.buf[idx_flag]) != 1:
            return None
        car = "".join([chr(self.buf[idx_car + 0]), chr(self.buf[idx_car + 1]), chr(self.buf[idx_car + 2])])
        rot = int(self.buf[idx_rot])
        pos = int(self.buf[idx_pos])
        if clear:
            self.buf[idx_flag] = 0
        return (car, rot, pos)

    # DS/WS wrappers
    def write_ds1(self, car_no, rot, pos, block=True, timeout=0.2):
        return self._write_wheel(IDX_DS1_FLAG, IDX_DS1_CAR, IDX_DS1_ROT, IDX_DS1_POS, car_no, rot, pos, block, timeout)

    def write_ds2(self, car_no, rot, pos, block=True, timeout=0.2):
        return self._write_wheel(IDX_DS2_FLAG, IDX_DS2_CAR, IDX_DS2_ROT, IDX_DS2_POS, car_no, rot, pos, block, timeout)

    def write_ws1(self, car_no, rot, pos, block=True, timeout=0.2):
        return self._write_wheel(IDX_WS1_FLAG, IDX_WS1_CAR, IDX_WS1_ROT, IDX_WS1_POS, car_no, rot, pos, block, timeout)

    def write_ws2(self, car_no, rot, pos, block=True, timeout=0.2):
        return self._write_wheel(IDX_WS2_FLAG, IDX_WS2_CAR, IDX_WS2_ROT, IDX_WS2_POS, car_no, rot, pos, block, timeout)

    def read_ds1(self, clear=True):
        return self._read_wheel(IDX_DS1_FLAG, IDX_DS1_CAR, IDX_DS1_ROT, IDX_DS1_POS, clear)

    def read_ds2(self, clear=True):
        return self._read_wheel(IDX_DS2_FLAG, IDX_DS2_CAR, IDX_DS2_ROT, IDX_DS2_POS, clear)

    def read_ws1(self, clear=True):
        return self._read_wheel(IDX_WS1_FLAG, IDX_WS1_CAR, IDX_WS1_ROT, IDX_WS1_POS, clear)

    def read_ws2(self, clear=True):
        return self._read_wheel(IDX_WS2_FLAG, IDX_WS2_CAR, IDX_WS2_ROT, IDX_WS2_POS, clear)
