# controllers/wheel_controller.py
import json
from datetime import datetime
from utils.wheel_status_utils import judge_one_wheel, combine_overall_wheel_status
from utils.image_utils import ws_wheel1_path, ds_wheel1_path, save_bgr_image_to_file


class WheelController:
    def __init__(self, table_manager):
        self.table = table_manager

        self.pending = {}  # car_no -> {"WS":(s1,s2), "DS":(s1,s2)}

        self.ws_status_map = {}   # car_no -> (s1,s2)
        self.ds_status_map = {}   # car_no -> (s1,s2)
        self.ws_image_map = {}    # car_no -> path
        self.ds_image_map = {}    # car_no -> path

        self.latest_ws_bgr = None
        self.latest_ds_bgr = None

    def update_latest_frame(self, pos, bgr):
        if pos == "WS":
            self.latest_ws_bgr = bgr
        else:
            self.latest_ds_bgr = bgr

    def handle_message(self, pos, text):
        if not isinstance(text, str):
            return None

        text_str = text.strip()
        if not text_str:
            return None

        try:
            data = json.loads(text_str)
        except Exception:
            return None

        if data.get("type") != "wheel_status":
            return None

        car_no = data.get("car_no")
        if not car_no:
            return None

        car_no_str = str(car_no).strip()

        w1_rot = data.get("wheel_1st_rotation", 0)
        w1_pos = data.get("wheel_1st_position", 0)
        w2_rot = data.get("wheel_2nd_rotation", 0)
        w2_pos = data.get("wheel_2nd_position", 0)

        status_1st = judge_one_wheel(w1_rot, w1_pos)
        status_2nd = judge_one_wheel(w2_rot, w2_pos)

        # 상태 저장(항상)
        if pos == "WS":
            self.ws_status_map[car_no_str] = (status_1st, status_2nd)
        else:
            self.ds_status_map[car_no_str] = (status_1st, status_2nd)

        # 휠 이미지 저장(최초 1회)
        self._save_wheel_image_if_needed(pos, car_no_str)

        # 테이블 반영 (없으면 pending)
        ok = self.table.update_wheel_status(car_no_str, pos, status_1st, status_2nd)
        if not ok:
            if car_no_str not in self.pending:
                self.pending[car_no_str] = {}
            self.pending[car_no_str][pos] = (status_1st, status_2nd)

        return {"car_no": car_no_str, "status_1st": status_1st, "status_2nd": status_2nd}

    def _save_wheel_image_if_needed(self, pos, car_no_str):
        ts = datetime.now()

        if pos == "WS":
            if car_no_str in self.ws_image_map:
                return
            bgr = self.latest_ws_bgr
            if bgr is None:
                return
            path = ws_wheel1_path(ts, car_no_str)
            if save_bgr_image_to_file(bgr, path):
                self.ws_image_map[car_no_str] = path
            return

        if car_no_str in self.ds_image_map:
            return
        bgr = self.latest_ds_bgr
        if bgr is None:
            return
        path = ds_wheel1_path(ts, car_no_str)
        if save_bgr_image_to_file(bgr, path):
            self.ds_image_map[car_no_str] = path

    def apply_pending_to_table(self, car_no_str):
        if car_no_str not in self.pending:
            return

        info = self.pending.get(car_no_str, {})
        if "WS" in info:
            s1, s2 = info["WS"]
            self.table.update_wheel_status(car_no_str, "WS", s1, s2)

        if "DS" in info:
            s1, s2 = info["DS"]
            self.table.update_wheel_status(car_no_str, "DS", s1, s2)

        del self.pending[car_no_str]

    def attach_wheel_info_to_record(self, rec):
        car_no_str = str(rec.get("car_no", "")).strip()

        ws_w1 = ws_w2 = ""
        ds_w1 = ds_w2 = ""
        img_ws = ""
        img_ds = ""

        if car_no_str in self.ws_status_map:
            ws_w1, ws_w2 = self.ws_status_map.get(car_no_str, ("", ""))
        if car_no_str in self.ds_status_map:
            ds_w1, ds_w2 = self.ds_status_map.get(car_no_str, ("", ""))

        if car_no_str in self.ws_image_map:
            img_ws = self.ws_image_map.get(car_no_str, "")
        if car_no_str in self.ds_image_map:
            img_ds = self.ds_image_map.get(car_no_str, "")

        rec["ws_wheel1_status"] = ws_w1
        rec["ws_wheel2_status"] = ws_w2
        rec["ds_wheel1_status"] = ds_w1
        rec["ds_wheel2_status"] = ds_w2
        rec["img_ws_wheel_path"] = img_ws
        rec["img_ds_wheel_path"] = img_ds

        overall = combine_overall_wheel_status(ws_w1, ws_w2, ds_w1, ds_w2)

        # 메모리 정리(한 번 쓴 대차는 제거)
        self.ws_status_map.pop(car_no_str, None)
        self.ds_status_map.pop(car_no_str, None)
        self.ws_image_map.pop(car_no_str, None)
        self.ds_image_map.pop(car_no_str, None)

        return overall
