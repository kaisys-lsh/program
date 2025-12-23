# controllers/wheel_controller.py
import json
from datetime import datetime

from utils.wheel_status_utils import judge_one_wheel, combine_overall_wheel_status
from utils.image_utils import ws_wheel1_path, ds_wheel1_path, save_bgr_image_to_file


class WheelController:
    def __init__(self, table_manager):
        self.table = table_manager

        # car_no -> {"WS":(s1,s2), "DS":(s1,s2)}
        self.pending = {}

        # car_no -> (s1,s2)
        self.ws_status_map = {}
        self.ds_status_map = {}

        # car_no -> path
        self.ws_image_map = {}
        self.ds_image_map = {}

        self.latest_ws_bgr = None
        self.latest_ds_bgr = None

    def update_latest_frame(self, pos, bgr):
        if pos == "WS":
            self.latest_ws_bgr = bgr
        else:
            self.latest_ds_bgr = bgr

    def _normalize_car_no(self, car_no_str):
        """
        서버 미검출: "FFF" -> wagon_controller record와 맞추기 위해 "none"으로 통일.
        (wagon_controller는 "NONE"을 입력받으면 record의 car_no를 "none"으로 만든다)
        """
        s = (car_no_str or "").strip()
        if not s:
            return ""
        if s == "FFF":
            return "none"
        if s == "NONE":
            return "none"
        return s

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

        msg_type = data.get("type", "")

        # pos 방어 (main에서 넘기지만, 혹시 빠졌을 때 대비)
        if pos not in ("WS", "DS"):
            pos = str(data.get("pos", "")).strip()

        if pos not in ("WS", "DS"):
            return None

        # ----------------------------
        # 1) 신규 포맷: wheel_event (flat)
        # ----------------------------
        if msg_type == "wheel_event":
            car_no = data.get("wheel_car_no")
            if car_no is None:
                car_no = data.get("car_no")

            w1_rot = data.get("wheel_1st_rotation", 0)
            w1_pos = data.get("wheel_1st_position", 0)
            w2_rot = data.get("wheel_2nd_rotation", 0)
            w2_pos = data.get("wheel_2nd_position", 0)

        # ----------------------------
        # 2) 신규 포맷: car_update (nested)
        # ----------------------------
        elif msg_type == "car_update":
            car_no = data.get("car_no")

            wheel = data.get("wheel", {})
            if wheel is None or not isinstance(wheel, dict):
                wheel = {}

            w1_rot = wheel.get("wheel_1st_rotation", 0)
            w1_pos = wheel.get("wheel_1st_position", 0)
            w2_rot = wheel.get("wheel_2nd_rotation", 0)
            w2_pos = wheel.get("wheel_2nd_position", 0)

        # ----------------------------
        # 3) 구버전 호환: wheel_status
        # ----------------------------
        elif msg_type == "wheel_status":
            car_no = data.get("car_no")

            w1_rot = data.get("wheel_1st_rotation", 0)
            w1_pos = data.get("wheel_1st_position", 0)
            w2_rot = data.get("wheel_2nd_rotation", 0)
            w2_pos = data.get("wheel_2nd_position", 0)

        else:
            return None

        if not car_no:
            return None

        car_no_str = self._normalize_car_no(str(car_no))

        if not car_no_str:
            return None

        status_1st = judge_one_wheel(w1_rot, w1_pos)
        status_2nd = judge_one_wheel(w2_rot, w2_pos)

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
