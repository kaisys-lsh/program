# controllers/wagon_controller.py
import re
from datetime import datetime
from utils.image_utils import (
    ws_car1_path,
    ws_leak1_path, ds_leak1_path,
    ws_leak2_path, ds_leak2_path,
    save_bgr_image_to_file
)


class WagonController:
    def __init__(self, delay_count, on_set_car_label, on_record_ready):
        self.delay_count = int(delay_count)
        self.on_set_car_label = on_set_car_label
        self.on_record_ready = on_record_ready

        self.current_label = None

        self.in_wagon = False
        self.cam1_pending_capture = False
        self.current_cam1_path = ""

        self.current_peak_db_ws1 = None
        self.current_peak_db_ds1 = None
        self.peak_ws1_bgr = None
        self.peak_ds1_bgr = None

        self.current_peak_db_ws2 = None
        self.current_peak_db_ds2 = None
        self.peak_ws2_bgr = None
        self.peak_ds2_bgr = None

        self.latest_frame_cam1_bgr = None
        self.latest_frame_ws1_bgr = None
        self.latest_frame_ds1_bgr = None
        self.latest_frame_ws2_bgr = None
        self.latest_frame_ds2_bgr = None

        self.car_queue = []

    # ---------- input: frames ----------
    def update_latest_frame(self, cam_id, bgr):
        if cam_id == "cam1":
            self.latest_frame_cam1_bgr = bgr
        elif cam_id == "ws1":
            self.latest_frame_ws1_bgr = bgr
        elif cam_id == "ds1":
            self.latest_frame_ds1_bgr = bgr
        elif cam_id == "ws2":
            self.latest_frame_ws2_bgr = bgr
        elif cam_id == "ds2":
            self.latest_frame_ds2_bgr = bgr

    # ---------- input: dB ----------
    def on_db(self, cam_id, db_value):
        try:
            v = float(db_value)
        except Exception:
            v = 0.0

        if cam_id == "ws1":
            if self.in_wagon and ((self.current_peak_db_ws1 is None) or (v > self.current_peak_db_ws1)):
                self.current_peak_db_ws1 = v
                if self.latest_frame_ws1_bgr is not None:
                    self.peak_ws1_bgr = self.latest_frame_ws1_bgr.copy()
            return

        if cam_id == "ds1":
            if self.in_wagon and ((self.current_peak_db_ds1 is None) or (v > self.current_peak_db_ds1)):
                self.current_peak_db_ds1 = v
                if self.latest_frame_ds1_bgr is not None:
                    self.peak_ds1_bgr = self.latest_frame_ds1_bgr.copy()
            return

        if cam_id == "ws2":
            if self.in_wagon and (len(self.car_queue) >= (self.delay_count - 1)):
                if (self.current_peak_db_ws2 is None) or (v > self.current_peak_db_ws2):
                    self.current_peak_db_ws2 = v
                    if self.latest_frame_ws2_bgr is not None:
                        self.peak_ws2_bgr = self.latest_frame_ws2_bgr.copy()
            return

        if cam_id == "ds2":
            if self.in_wagon and (len(self.car_queue) >= (self.delay_count - 1)):
                if (self.current_peak_db_ds2 is None) or (v > self.current_peak_db_ds2):
                    self.current_peak_db_ds2 = v
                    if self.latest_frame_ds2_bgr is not None:
                        self.peak_ds2_bgr = self.latest_frame_ds2_bgr.copy()

    # ---------- input: ZMQ START/END ----------
    def on_cam_message(self, text):
        raw = (text or "").strip()
        if not raw:
            return

        if raw == "START":
            self._on_wagon_start()
            return

        if raw == "NONE" or re.fullmatch(r"\d{3}", raw):
            self._on_wagon_end(raw)
            return

        m = re.search(r"\b(\d{3})\b", raw)
        if m:
            self._on_wagon_end(m.group(1))

    def _on_wagon_start(self):
        self.in_wagon = True
        self.cam1_pending_capture = True

        self.on_set_car_label("...")

        self.current_peak_db_ws1 = None
        self.current_peak_db_ds1 = None
        self.peak_ws1_bgr = None
        self.peak_ds1_bgr = None

        # 네 코드처럼 즉시 캡쳐(원하면 UI에서 QTimer로 1초 딜레이 걸어도 됨)
        self._capture_cam1()

    def _capture_cam1(self):
        if not self.cam1_pending_capture:
            return
        if self.latest_frame_cam1_bgr is None:
            return

        ts = datetime.now()
        car_no_for_path = self.current_label if self.current_label else "none"

        path1 = ws_car1_path(ts, car_no_for_path)
        if save_bgr_image_to_file(self.latest_frame_cam1_bgr, path1):
            self.current_cam1_path = path1

        self.cam1_pending_capture = False

    def _on_wagon_end(self, raw_code):
        # START 없이 END가 들어온 경우
        if not self.in_wagon:
            if raw_code == "NONE":
                self.on_set_car_label("N")
                self.current_label = "none"
            else:
                self.on_set_car_label(raw_code)
                self.current_label = raw_code
            return

        if raw_code == "NONE":
            car_no = "none"
            display_label = "N"
        else:
            car_no = raw_code
            display_label = car_no

        self.on_set_car_label(display_label)
        self.current_label = car_no

        if self.cam1_pending_capture:
            self._capture_cam1()

        self._push_current_record_to_queue()
        self._queue_push()

        self.in_wagon = False
        self._reset_for_new_car()

    def _reset_for_new_car(self):
        self.current_cam1_path = ""
        self.current_peak_db_ws1 = None
        self.current_peak_db_ds1 = None
        self.peak_ws1_bgr = None
        self.peak_ds1_bgr = None

    def _push_current_record_to_queue(self):
        car_no = self.current_label or ""
        ts = datetime.now()

        rec = {
            "ts": ts,
            "car_no": car_no,
            "img_cam1_path": self.current_cam1_path or "",

            "ws1_db": float(self.current_peak_db_ws1 or 0.0),
            "ds1_db": float(self.current_peak_db_ds1 or 0.0),
            "img_ws1_path": "",
            "img_ds1_path": "",

            "ws2_db": 0.0,
            "ds2_db": 0.0,
            "img_ws2_path": "",
            "img_ds2_path": "",

            # 기존 DBWriter 호환 키
            "dba": float(self.current_peak_db_ws1 or 0.0),
            "dbb": float(self.current_peak_db_ds1 or 0.0),
            "img_a_path": "",
            "img_b_path": "",
        }

        if self.peak_ws1_bgr is not None:
            pathA = ws_leak1_path(ts, car_no)
            if save_bgr_image_to_file(self.peak_ws1_bgr, pathA):
                rec["img_ws1_path"] = pathA
                rec["img_a_path"] = pathA

        if self.peak_ds1_bgr is not None:
            pathB = ds_leak1_path(ts, car_no)
            if save_bgr_image_to_file(self.peak_ds1_bgr, pathB):
                rec["img_ds1_path"] = pathB
                rec["img_b_path"] = pathB

        self.car_queue.append(rec)

    def _queue_push(self):
        while len(self.car_queue) >= self.delay_count:
            rec = self.car_queue.pop(0)
            car_no = rec.get("car_no", "")
            ts = datetime.now()

            if self.peak_ws2_bgr is not None:
                pathA = ws_leak2_path(ts, car_no)
                if save_bgr_image_to_file(self.peak_ws2_bgr, pathA):
                    rec["img_ws2_path"] = pathA

            if self.peak_ds2_bgr is not None:
                pathB = ds_leak2_path(ts, car_no)
                if save_bgr_image_to_file(self.peak_ds2_bgr, pathB):
                    rec["img_ds2_path"] = pathB

            rec["ws2_db"] = float(self.current_peak_db_ws2 or 0.0)
            rec["ds2_db"] = float(self.current_peak_db_ds2 or 0.0)

            self.on_record_ready(rec)

            self.current_peak_db_ws2 = None
            self.current_peak_db_ds2 = None
            self.peak_ws2_bgr = None
            self.peak_ds2_bgr = None

    def flush_remaining_records(self):
        # closeEvent에서 남은 것들 DB로 보내려면 이걸 호출
        left = []
        while self.car_queue:
            left.append(self.car_queue.pop(0))
        return left
