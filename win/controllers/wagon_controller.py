# controllers/wagon_controller.py
import time
from datetime import datetime

from utils.image_utils import (
    ws_car1_path,
    ws_leak1_path,
    ds_leak1_path,
    ws_leak2_path,
    ds_leak2_path,
    ws_wheel1_path,
    ds_wheel1_path,
    save_bgr_image_to_file,
)
from utils.wheel_status_utils import combine_overall_wheel_status


class WagonController:
    """
    역할
    - car_event START/END 로 "현재 대차 1구간" 세션을 만들고 종료 시 record 생성
    - START 후 snapshot_sec가 지나면 (cam1 + wheel ws/ds) 프레임을 '메모리로' 캡처
      -> END 시점에 car_no를 알고 저장(파일명 매칭)
    - 1구간(WS1/DS1) dB peak + 해당 peak 프레임 저장
    - 2구간(WS2/DS2) dB peak는 "큐 길이(delay_count)"로 매칭해서 저장
      (큐 pop 시점에 2구간 peak를 해당 대차에 귀속)
    - wheel_event(WS/DS) 상태가 둘 다 들어오면 stage1(DB insert) 준비
    - 해당 대차가 2구간까지 매칭되면 final(HMI 표시 + DB update) 준비
    """

    def __init__(
        self,
        delay_count,
        snapshot_sec,
        on_set_car_label=None,
        on_stage1_ready=None,
        on_final_ready=None,
    ):
        self.delay_count = int(delay_count) if delay_count else 2
        if self.delay_count < 1:
            self.delay_count = 1

        try:
            self.snapshot_sec = float(snapshot_sec)
        except Exception:
            self.snapshot_sec = 1.0

        self.on_set_car_label = on_set_car_label
        self.on_stage1_ready = on_stage1_ready
        self.on_final_ready = on_final_ready

        # ----------------------------
        # 최신 프레임 (RTSP에서 계속 업데이트)
        # ----------------------------
        self.latest_cam1_bgr = None
        self.latest_ws1_bgr = None
        self.latest_ds1_bgr = None
        self.latest_ws2_bgr = None
        self.latest_ds2_bgr = None
        self.latest_wheel_ws_bgr = None
        self.latest_wheel_ds_bgr = None

        # ----------------------------
        # 현재 1구간 세션 상태(START~END)
        # ----------------------------
        self.in_wagon = False
        self._start_mono = 0.0
        self._snap_due_mono = 0.0
        self._snap_taken = False
        self._snap_cam1_bgr = None
        self._snap_wheel_ws_bgr = None
        self._snap_wheel_ds_bgr = None

        # 1구간 peak (WS1/DS1)
        self._peak_ws1_db = 0.0
        self._peak_ds1_db = 0.0
        self._peak_ws1_bgr = None
        self._peak_ds1_bgr = None

        # 2구간 peak (WS2/DS2) - "현재 2구간 대상"의 peak
        self._peak_ws2_db = 0.0
        self._peak_ds2_db = 0.0
        self._peak_ws2_bgr = None
        self._peak_ds2_bgr = None

        # ----------------------------
        # END가 온 대차들을 순서대로 쌓는 큐(2구간 매칭용)
        # - item: event_id (str)
        # ----------------------------
        self._car_queue = []

        # ----------------------------
        # event_id -> record(대차 1건)
        # ----------------------------
        self._records = {}  # event_id -> rec(dict)

        # ----------------------------
        # wheel 상태 저장 (event_id 기준)
        # ----------------------------
        self._wheel_map = {}  # event_id -> {"car_no":str, "WS":(s1,s2), "DS":(s1,s2)}

    # -------------------------------------------------
    # 외부에서 RTSP 프레임 들어올 때 호출
    # -------------------------------------------------
    def update_latest_frame(self, cam_id, bgr):
        if cam_id == "cam1":
            self.latest_cam1_bgr = bgr
        elif cam_id == "ws1":
            self.latest_ws1_bgr = bgr
        elif cam_id == "ds1":
            self.latest_ds1_bgr = bgr
        elif cam_id == "ws2":
            self.latest_ws2_bgr = bgr
        elif cam_id == "ds2":
            self.latest_ds2_bgr = bgr
        elif cam_id == "wheel_ws":
            self.latest_wheel_ws_bgr = bgr
        elif cam_id == "wheel_ds":
            self.latest_wheel_ds_bgr = bgr

        # START 이후 snapshot_sec 지났으면 스냅샷 캡처(메모리)
        self._maybe_take_snapshot()

    def _maybe_take_snapshot(self):
        if not self.in_wagon:
            return
        if self._snap_taken:
            return

        now_mono = time.monotonic()
        if now_mono < self._snap_due_mono:
            return

        # 3개 다 있어야 "동시에" 캡처로 간주
        if self.latest_cam1_bgr is None:
            return
        if self.latest_wheel_ws_bgr is None:
            return
        if self.latest_wheel_ds_bgr is None:
            return

        # 메모리에 복사(END에서 car_no 알고 저장)
        try:
            self._snap_cam1_bgr = self.latest_cam1_bgr.copy()
        except Exception:
            self._snap_cam1_bgr = self.latest_cam1_bgr

        try:
            self._snap_wheel_ws_bgr = self.latest_wheel_ws_bgr.copy()
        except Exception:
            self._snap_wheel_ws_bgr = self.latest_wheel_ws_bgr

        try:
            self._snap_wheel_ds_bgr = self.latest_wheel_ds_bgr.copy()
        except Exception:
            self._snap_wheel_ds_bgr = self.latest_wheel_ds_bgr

        self._snap_taken = True

    # -------------------------------------------------
    # 외부에서 dB 들어올 때 호출
    # -------------------------------------------------
    def on_db(self, cam_id, db_value):
        try:
            fv = float(db_value)
        except Exception:
            fv = 0.0

        if self.in_wagon:
            # 1구간 peak
            if cam_id == "ws1":
                if fv >= self._peak_ws1_db:
                    self._peak_ws1_db = fv
                    self._peak_ws1_bgr = self.latest_ws1_bgr
            elif cam_id == "ds1":
                if fv >= self._peak_ds1_db:
                    self._peak_ds1_db = fv
                    self._peak_ds1_bgr = self.latest_ds1_bgr

            # 2구간 peak (큐 길이로 "2구간 대상이 존재"할 때만 갱신)
            if len(self._car_queue) >= (self.delay_count - 1):
                if cam_id == "ws2":
                    if fv >= self._peak_ws2_db:
                        self._peak_ws2_db = fv
                        self._peak_ws2_bgr = self.latest_ws2_bgr
                elif cam_id == "ds2":
                    if fv >= self._peak_ds2_db:
                        self._peak_ds2_db = fv
                        self._peak_ds2_bgr = self.latest_ds2_bgr

    # -------------------------------------------------
    # car_event 처리(START/END)
    # -------------------------------------------------
    def on_car_event(self, data):
        if not isinstance(data, dict):
            return

        if data.get("type") != "car_event":
            return

        ev = str(data.get("event", "")).strip().upper()
        if ev == "START":
            self._on_start()
            return

        if ev == "END":
            event_id = data.get("event_id")
            car_no = data.get("car_no")
            self._on_end(event_id, car_no)
            return

    def _on_start(self):
        self.in_wagon = True

        self._start_mono = time.monotonic()
        self._snap_due_mono = self._start_mono + self.snapshot_sec
        self._snap_taken = False
        self._snap_cam1_bgr = None
        self._snap_wheel_ws_bgr = None
        self._snap_wheel_ds_bgr = None

        # 1구간 peak reset
        self._peak_ws1_db = 0.0
        self._peak_ds1_db = 0.0
        self._peak_ws1_bgr = None
        self._peak_ds1_bgr = None

        # UI 라벨
        if self.on_set_car_label is not None:
            try:
                self.on_set_car_label("START")
            except Exception:
                pass

    def _normalize_car_no(self, car_no_raw):
        if car_no_raw is None:
            return "none"
        s = str(car_no_raw).strip()
        if not s:
            return "none"
        if s.upper() == "FFF":
            return "none"
        return s

    def _on_end(self, event_id, car_no_raw):
        # END는 "현재 세션 종료"
        self.in_wagon = False

        # event_id는 필수(없으면 유실로 처리)
        if not event_id:
            if self.on_set_car_label is not None:
                try:
                    self.on_set_car_label("END(no event_id)")
                except Exception:
                    pass
            return

        event_id_str = str(event_id).strip()
        car_no_str = self._normalize_car_no(car_no_raw)

        # UI 라벨
        if self.on_set_car_label is not None:
            try:
                if car_no_str == "none":
                    self.on_set_car_label("END: N")
                else:
                    self.on_set_car_label("END: {0}".format(car_no_str))
            except Exception:
                pass

        ts = datetime.now()

        # ----------------------------
        # END 시점에 스냅샷/peak 이미지 저장(파일)
        # ----------------------------
        img_car_path = ""
        img_ws_wheel_path = ""
        img_ds_wheel_path = ""
        img_ws1_path = ""
        img_ds1_path = ""

        # car snapshot
        car_bgr = self._snap_cam1_bgr if self._snap_cam1_bgr is not None else self.latest_cam1_bgr
        if car_bgr is not None:
            p = ws_car1_path(ts, car_no_str)
            if save_bgr_image_to_file(car_bgr, p):
                img_car_path = p

        # wheel snapshots (WS/DS)
        wws_bgr = self._snap_wheel_ws_bgr if self._snap_wheel_ws_bgr is not None else self.latest_wheel_ws_bgr
        if wws_bgr is not None:
            p = ws_wheel1_path(ts, car_no_str)
            if save_bgr_image_to_file(wws_bgr, p):
                img_ws_wheel_path = p

        wds_bgr = self._snap_wheel_ds_bgr if self._snap_wheel_ds_bgr is not None else self.latest_wheel_ds_bgr
        if wds_bgr is not None:
            p = ds_wheel1_path(ts, car_no_str)
            if save_bgr_image_to_file(wds_bgr, p):
                img_ds_wheel_path = p

        # leak1 peak frames (WS1/DS1)
        if self._peak_ws1_bgr is not None:
            p = ws_leak1_path(ts, car_no_str)
            if save_bgr_image_to_file(self._peak_ws1_bgr, p):
                img_ws1_path = p

        if self._peak_ds1_bgr is not None:
            p = ds_leak1_path(ts, car_no_str)
            if save_bgr_image_to_file(self._peak_ds1_bgr, p):
                img_ds1_path = p

        # ----------------------------
        # record 생성(2구간/휠은 나중에 채움)
        # ----------------------------
        rec = {
            "event_id": event_id_str,
            "ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "car_no": car_no_str,

            "ws1_db": float(self._peak_ws1_db),
            "ds1_db": float(self._peak_ds1_db),
            "ws2_db": 0.0,
            "ds2_db": 0.0,

            "img_car_path": img_car_path,
            "img_ws1_path": img_ws1_path,
            "img_ds1_path": img_ds1_path,
            "img_ws2_path": "",
            "img_ds2_path": "",

            # 휠(스냅샷 이미지 경로는 여기서 확보)
            "ws_wheel1_status": "",
            "ws_wheel2_status": "",
            "ds_wheel1_status": "",
            "ds_wheel2_status": "",
            "img_ws_wheel_path": img_ws_wheel_path,
            "img_ds_wheel_path": img_ds_wheel_path,

            # 내부 플래그
            "_stage1_ready": False,
            "_zone2_ready": False,
        }

        self._records[event_id_str] = rec

        # 2구간 매칭 큐에 event_id push
        self._car_queue.append(event_id_str)

        # wheel 상태가 이미 들어와있으면 stage1 만들기
        self._try_stage1(event_id_str)

        # 큐가 설정치 이상이면 pop -> 2구간 매칭
        self._try_pop_zone2()

    # -------------------------------------------------
    # wheel 상태(WS/DS) 업데이트
    # -------------------------------------------------
    def on_wheel_status(self, event_id, pos, status_1st, status_2nd, car_no_str=None):
        if not event_id:
            return
        event_id_str = str(event_id).strip()
        pos_str = str(pos).strip().upper()

        if event_id_str not in self._wheel_map:
            self._wheel_map[event_id_str] = {"car_no": "", "WS": None, "DS": None}

        if car_no_str is not None:
            self._wheel_map[event_id_str]["car_no"] = str(car_no_str).strip()

        if pos_str == "WS":
            self._wheel_map[event_id_str]["WS"] = (status_1st, status_2nd)
        elif pos_str == "DS":
            self._wheel_map[event_id_str]["DS"] = (status_1st, status_2nd)

        self._try_stage1(event_id_str)

    def _try_stage1(self, event_id_str):
        # END가 먼저 와서 record가 있어야 stage1 가능
        if event_id_str not in self._records:
            return

        rec = self._records[event_id_str]
        if rec.get("_stage1_ready", False):
            # 이미 stage1 emit 된 상태면, zone2 준비됐는지 체크만
            if rec.get("_zone2_ready", False):
                self._emit_final(event_id_str)
            return

        w = self._wheel_map.get(event_id_str)
        if w is None:
            return

        ws_pair = w.get("WS")
        ds_pair = w.get("DS")
        if ws_pair is None or ds_pair is None:
            return

        # stage1 채우기(휠)
        rec["ws_wheel1_status"] = ws_pair[0]
        rec["ws_wheel2_status"] = ws_pair[1]
        rec["ds_wheel1_status"] = ds_pair[0]
        rec["ds_wheel2_status"] = ds_pair[1]
        rec["_stage1_ready"] = True

        # stage1(DB insert) 콜백
        if self.on_stage1_ready is not None:
            try:
                self.on_stage1_ready(rec)
            except Exception:
                pass

        # zone2가 먼저 준비되어 있던 케이스면 바로 final
        if rec.get("_zone2_ready", False):
            self._emit_final(event_id_str)

    # -------------------------------------------------
    # 2구간 매칭 (큐 pop)
    # -------------------------------------------------
    def _try_pop_zone2(self):
        # 큐 길이가 설정치 이상이면 pop해서 2구간을 해당 대차에 귀속
        while len(self._car_queue) >= self.delay_count:
            target_id = self._car_queue.pop(0)

            rec = self._records.get(target_id)
            if rec is None:
                # 이상 케이스: peak reset 하고 넘어감
                self._reset_zone2_peak()
                continue

            ts = datetime.now()
            car_no_str = str(rec.get("car_no", "none")).strip()
            if not car_no_str:
                car_no_str = "none"

            # 2구간 peak 이미지 저장
            img_ws2_path = ""
            img_ds2_path = ""

            if self._peak_ws2_bgr is not None:
                p = ws_leak2_path(ts, car_no_str)
                if save_bgr_image_to_file(self._peak_ws2_bgr, p):
                    img_ws2_path = p

            if self._peak_ds2_bgr is not None:
                p = ds_leak2_path(ts, car_no_str)
                if save_bgr_image_to_file(self._peak_ds2_bgr, p):
                    img_ds2_path = p

            rec["ws2_db"] = float(self._peak_ws2_db)
            rec["ds2_db"] = float(self._peak_ds2_db)
            rec["img_ws2_path"] = img_ws2_path
            rec["img_ds2_path"] = img_ds2_path
            rec["_zone2_ready"] = True

            # 다음 대차를 위해 zone2 peak reset
            self._reset_zone2_peak()

            # stage1까지 준비되었으면 final emit
            if rec.get("_stage1_ready", False):
                self._emit_final(target_id)
            # stage1이 아직이면, stage1 준비되는 순간(_try_stage1)에서 final 처리됨

    def _reset_zone2_peak(self):
        self._peak_ws2_db = 0.0
        self._peak_ds2_db = 0.0
        self._peak_ws2_bgr = None
        self._peak_ds2_bgr = None

    # -------------------------------------------------
    # final emit (HMI 표시 + DB update)
    # -------------------------------------------------
    def _emit_final(self, event_id_str):
        rec = self._records.get(event_id_str)
        if rec is None:
            return

        # wheel overall 계산(버튼 표시용으로 main에서 쓰면 됨)
        ws_w1 = rec.get("ws_wheel1_status", "")
        ws_w2 = rec.get("ws_wheel2_status", "")
        ds_w1 = rec.get("ds_wheel1_status", "")
        ds_w2 = rec.get("ds_wheel2_status", "")
        rec["wheel_overall"] = combine_overall_wheel_status(ws_w1, ws_w2, ds_w1, ds_w2)

        if self.on_final_ready is not None:
            try:
                self.on_final_ready(rec)
            except Exception:
                pass

        # 정리(메모리 누적 방지)
        try:
            del self._records[event_id_str]
        except Exception:
            pass
        try:
            if event_id_str in self._wheel_map:
                del self._wheel_map[event_id_str]
        except Exception:
            pass

    # -------------------------------------------------
    # 종료 시 남은 것 처리용(선택)
    # -------------------------------------------------
    def flush_remaining_records(self):
        """
        종료 직전 남아있는 record 반환.
        - 아직 final 안 된 것들을 그대로 넘김(원하면 main에서 insert/update 처리)
        """
        left = []
        for k in list(self._records.keys()):
            rec = self._records.get(k)
            if rec is not None:
                left.append(rec)
        return left
