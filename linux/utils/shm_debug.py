# utils/shm_debug.py
# 공유메모리(0~49) 스냅샷 + 변경(diff) 로그 출력

import time
import threading

def _b(v):
    return int(v) & 0xFF

def _ascii3(buf, a, b, c):
    try:
        return chr(_b(buf[a])) + chr(_b(buf[b])) + chr(_b(buf[c]))
    except Exception:
        return "???"

def format_shm_0_49(buf):
    """
    너가 준 문서 구조(0~49) 그대로 사람이 읽기 쉽게 1줄 문자열로 만든다.
    """
    stop = _b(buf[0])
    car_flag = _b(buf[1])
    car_no = _ascii3(buf, 2, 3, 4)

    ds1_flag = _b(buf[10]); ds1_car = _ascii3(buf, 11,12,13); ds1_rot = _b(buf[16]); ds1_pos = _b(buf[17])
    ds2_flag = _b(buf[20]); ds2_car = _ascii3(buf, 21,22,23); ds2_rot = _b(buf[26]); ds2_pos = _b(buf[27])

    ws1_flag = _b(buf[30]); ws1_car = _ascii3(buf, 31,32,33); ws1_rot = _b(buf[36]); ws1_pos = _b(buf[37])
    ws2_flag = _b(buf[40]); ws2_car = _ascii3(buf, 41,42,43); ws2_rot = _b(buf[46]); ws2_pos = _b(buf[47])

    s = []
    s.append(f"STOP[0]={stop}")
    s.append(f"CAR(flag[1]={car_flag}, no[2:4]='{car_no}')")
    s.append(f"DS1(flag10={ds1_flag}, car='{ds1_car}', rot16={ds1_rot}, pos17={ds1_pos})")
    s.append(f"DS2(flag20={ds2_flag}, car='{ds2_car}', rot26={ds2_rot}, pos27={ds2_pos})")
    s.append(f"WS1(flag30={ws1_flag}, car='{ws1_car}', rot36={ws1_rot}, pos37={ws1_pos})")
    s.append(f"WS2(flag40={ws2_flag}, car='{ws2_car}', rot46={ws2_rot}, pos47={ws2_pos})")
    return " | ".join(s)

def diff_indices(prev, cur, watch_idxs):
    changed = []
    for i in watch_idxs:
        pv = int(prev[i])
        cv = int(cur[i])
        if pv != cv:
            changed.append((i, pv, cv))
    return changed

class ShmMonitorThread(threading.Thread):
    """
    - buf(=np.ndarray or shm.buf view)에서 0~49를 주기적으로 읽고
    - 값이 바뀌면 diff + 전체 구조를 출력
    """
    def __init__(self, name, buf, poll_sec=0.05, print_full_on_change=True):
        super().__init__(daemon=True)
        self.name_tag = str(name)
        self.buf = buf
        self.poll_sec = float(poll_sec)
        self.print_full_on_change = bool(print_full_on_change)
        self._run = True

        # 0~49 중 의미있는 곳 위주로 watch
        self.watch = [
            0,1,2,3,4,
            10,11,12,13,16,17,
            20,21,22,23,26,27,
            30,31,32,33,36,37,
            40,41,42,43,46,47
        ]

        self._prev = None

    def stop(self):
        self._run = False

    def run(self):
        # 첫 스냅샷
        self._prev = bytearray([_b(self.buf[i]) for i in range(50)])
        print(f"[SHM-MON:{self.name_tag}] start")
        print(f"[SHM-MON:{self.name_tag}] {format_shm_0_49(self.buf)}")

        while self._run:
            cur = bytearray([_b(self.buf[i]) for i in range(50)])

            ch = diff_indices(self._prev, cur, self.watch)
            if ch:
                # diff 출력
                diff_txt = ", ".join([f"{i}:{pv}->{cv}" for (i,pv,cv) in ch])
                print(f"[SHM-MON:{self.name_tag}] CHANGED: {diff_txt}")

                if self.print_full_on_change:
                    print(f"[SHM-MON:{self.name_tag}] {format_shm_0_49(self.buf)}")

                self._prev = cur

            time.sleep(self.poll_sec)
