# controllers/wagon_controller.py
# -*- coding: utf-8 -*-
import os
import time
from datetime import datetime
import threading

import cv2
import pymysql


class WagonController:
    _COL_TYPES = {
        "event_id": "VARCHAR(64) NOT NULL",
        "ts": "DATETIME NULL DEFAULT NULL",
        "car_no": "VARCHAR(32) NULL DEFAULT NULL",

        "ws1_db": "DOUBLE NULL DEFAULT NULL",
        "ds1_db": "DOUBLE NULL DEFAULT NULL",
        "ws2_db": "DOUBLE NULL DEFAULT NULL",
        "ds2_db": "DOUBLE NULL DEFAULT NULL",

        "img_car_path": "VARCHAR(255) NULL DEFAULT NULL",
        "img_ws1_path": "VARCHAR(255) NULL DEFAULT NULL",
        "img_ds1_path": "VARCHAR(255) NULL DEFAULT NULL",
        "img_ws2_path": "VARCHAR(255) NULL DEFAULT NULL",
        "img_ds2_path": "VARCHAR(255) NULL DEFAULT NULL",

        "ws_wheel1_status": "VARCHAR(32) NULL DEFAULT NULL",
        "ws_wheel2_status": "VARCHAR(32) NULL DEFAULT NULL",
        "ds_wheel1_status": "VARCHAR(32) NULL DEFAULT NULL",
        "ds_wheel2_status": "VARCHAR(32) NULL DEFAULT NULL",
        "img_ws_wheel_path": "VARCHAR(255) NULL DEFAULT NULL",
        "img_ds_wheel_path": "VARCHAR(255) NULL DEFAULT NULL",

        "seq_no": "BIGINT NOT NULL DEFAULT 0",
        "start_done": "TINYINT NOT NULL DEFAULT 0",
        "car_no_done": "TINYINT NOT NULL DEFAULT 0",
        "zone1_done": "TINYINT NOT NULL DEFAULT 0",
        "zone2_done": "TINYINT NOT NULL DEFAULT 0",
        "wheel_ws_done": "TINYINT NOT NULL DEFAULT 0",
        "wheel_ds_done": "TINYINT NOT NULL DEFAULT 0",
        "ui_done": "TINYINT NOT NULL DEFAULT 0",
    }

    def __init__(
        self,
        delay_count,
        snapshot_sec,
        on_set_car_label,
        on_stage1_ready,
        db_host,
        db_port,
        db_user,
        db_pw,
        db_name="posco",
        table_name="data",
    ):
        self.delay_count = int(delay_count)
        self.snapshot_sec = float(snapshot_sec) if snapshot_sec is not None else 0.0

        self.on_set_car_label = on_set_car_label
        self.on_stage1_ready = on_stage1_ready

        self.db_host = db_host
        self.db_port = int(db_port)
        self.db_user = db_user
        self.db_pw = db_pw
        self.db_name = db_name
        self.table_name = table_name

        self._lock = threading.Lock()

        self.current_event_id = ""
        self.current_seq_no = 0

        self.latest_frames = {}

        self.zone1_peak = {"ws1": 0.0, "ds1": 0.0}
        self.zone2_peak = {"ws2": 0.0, "ds2": 0.0}
        self.zone1_peak_frame = {"ws1": None, "ds1": None}
        self.zone2_peak_frame = {"ws2": None, "ds2": None}

        self.save_root = os.path.join(os.getcwd(), "DATA")
        self._ensure_dir(self.save_root)

    # ------------------------------------------------------------
    # DB ensure
    # ------------------------------------------------------------
    def _connect_server(self):
        return pymysql.connect(
            host=self.db_host,
            port=self.db_port,
            user=self.db_user,
            password=self.db_pw,
            autocommit=True,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )

    def _get_conn(self):
        return pymysql.connect(
            host=self.db_host,
            port=self.db_port,
            user=self.db_user,
            password=self.db_pw,
            database=self.db_name,
            autocommit=True,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )

    def _ensure_db_and_table(self):
        # 1) DB 생성
        conn = None
        try:
            conn = self._connect_server()
            with conn.cursor() as cur:
                cur.execute(
                    "CREATE DATABASE IF NOT EXISTS `{}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci".format(self.db_name)
                )
        except Exception:
            pass
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

        # 2) TABLE 생성/보강
        conn2 = None
        try:
            conn2 = self._get_conn()

            cols_sql = []
            cols_sql.append("id BIGINT NOT NULL AUTO_INCREMENT")
            cols_sql.append("event_id VARCHAR(64) NOT NULL")
            for k, t in self._COL_TYPES.items():
                if k == "event_id":
                    continue
                cols_sql.append(f"`{k}` {t}")
            cols_sql.append("PRIMARY KEY(id)")
            cols_sql.append("UNIQUE KEY uq_event (event_id)")
            cols_sql.append("INDEX idx_ts (ts)")
            cols_sql.append("INDEX idx_car (car_no)")

            sql_create = f"""
            CREATE TABLE IF NOT EXISTS `{self.table_name}` (
                {", ".join(cols_sql)}
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
            with conn2.cursor() as cur:
                cur.execute(sql_create)

            def _exec_ignore(sql):
                try:
                    with conn2.cursor() as cur:
                        cur.execute(sql)
                except Exception:
                    pass

            _exec_ignore(f"ALTER TABLE `{self.table_name}` ADD UNIQUE KEY uq_event (event_id)")
            for col_name, col_type in self._COL_TYPES.items():
                if col_name == "event_id":
                    continue
                _exec_ignore(f"ALTER TABLE `{self.table_name}` ADD COLUMN `{col_name}` {col_type}")

        except Exception:
            pass
        finally:
            try:
                if conn2:
                    conn2.close()
            except Exception:
                pass

    # ------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------
    def _alloc_next_seq_no(self):
        # ✅ 테이블 없으면 생성 후 MAX(seq_no) 조회
        self._ensure_db_and_table()

        conn = None
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(f"SELECT COALESCE(MAX(seq_no), 0) AS m FROM `{self.table_name}`")
                row = cur.fetchone()
                if row and "m" in row:
                    return int(row["m"]) + 1
        except Exception:
            pass
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

        with self._lock:
            self.current_seq_no = self.current_seq_no + 1 if self.current_seq_no > 0 else 1
            return self.current_seq_no

    def _find_event_id_by_seq_no(self, seq_no):
        # ✅ 테이블 없으면 생성 후 조회
        self._ensure_db_and_table()

        conn = None
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT event_id FROM `{self.table_name}` WHERE seq_no=%s LIMIT 1",
                    (int(seq_no),),
                )
                row = cur.fetchone()
                if row:
                    return str(row.get("event_id", "")).strip()
        except Exception:
            pass
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
        return ""

    # ------------------------------------------------------------
    # image save helpers
    # ------------------------------------------------------------
    def _ensure_dir(self, d):
        try:
            if not os.path.exists(d):
                os.makedirs(d)
        except Exception:
            pass

    def _make_path(self, prefix, event_id):
        day = datetime.now().strftime("%Y%m%d")
        out_dir = os.path.join(self.save_root, day)
        self._ensure_dir(out_dir)
        ts = datetime.now().strftime("%H%M%S_%f")
        return os.path.join(out_dir, f"{prefix}_{event_id}_{ts}.jpg")

    def _save_bgr(self, bgr, prefix, event_id):
        if bgr is None:
            return ""
        path = self._make_path(prefix, event_id)
        try:
            cv2.imwrite(path, bgr)
            return path
        except Exception:
            return ""

    # ------------------------------------------------------------
    # public: frame / db / zmq events
    # ------------------------------------------------------------
    def update_latest_frame(self, cam_id, bgr):
        if not cam_id or bgr is None:
            return
        with self._lock:
            self.latest_frames[str(cam_id)] = bgr

    def on_db(self, cam_id, value):
        if cam_id not in ("ws1", "ds1", "ws2", "ds2"):
            return
        try:
            fv = float(value)
        except Exception:
            fv = 0.0

        with self._lock:
            if cam_id in ("ws1", "ds1"):
                if fv >= float(self.zone1_peak.get(cam_id, 0.0)):
                    self.zone1_peak[cam_id] = fv
                    self.zone1_peak_frame[cam_id] = self.latest_frames.get(cam_id, None)
            else:
                if fv >= float(self.zone2_peak.get(cam_id, 0.0)):
                    self.zone2_peak[cam_id] = fv
                    self.zone2_peak_frame[cam_id] = self.latest_frames.get(cam_id, None)

    def on_car_event(self, data):
        if not isinstance(data, dict):
            return
        ev = str(data.get("event", "")).strip().upper()
        event_id = str(data.get("event_id", "") or "").strip()
        if not ev or not event_id:
            return
        if ev == "START":
            self._handle_start(event_id)
        elif ev == "END":
            self._handle_end(event_id)

    def on_car_no(self, data):
        if not isinstance(data, dict):
            return
        event_id = str(data.get("event_id", "") or "").strip()
        car_no = str(data.get("car_no", "") or "").strip()
        if not event_id:
            return
        if not car_no:
            car_no = "NONE"
        try:
            if self.on_set_car_label:
                self.on_set_car_label(car_no)
        except Exception:
            pass
        self._emit_patch({"event_id": event_id, "car_no": car_no, "car_no_done": 1})

    def on_wheel_status(self, event_id, pos, status_1st, status_2nd, car_no_str=""):
        eid = str(event_id or "").strip()
        if not eid:
            return
        p = str(pos or "").strip().upper()

        patch = {"event_id": eid}
        if car_no_str:
            patch["car_no"] = str(car_no_str).strip()

        if p == "WS":
            patch["ws_wheel1_status"] = str(status_1st or "")
            patch["ws_wheel2_status"] = str(status_2nd or "")
            patch["wheel_ws_done"] = 1
        elif p == "DS":
            patch["ds_wheel1_status"] = str(status_1st or "")
            patch["ds_wheel2_status"] = str(status_2nd or "")
            patch["wheel_ds_done"] = 1
        else:
            return

        self._emit_patch(patch)

    # ------------------------------------------------------------
    # internal: START / END
    # ------------------------------------------------------------
    def _reset_zone1(self):
        self.zone1_peak["ws1"] = 0.0
        self.zone1_peak["ds1"] = 0.0
        self.zone1_peak_frame["ws1"] = None
        self.zone1_peak_frame["ds1"] = None

    def _reset_zone2(self):
        self.zone2_peak["ws2"] = 0.0
        self.zone2_peak["ds2"] = 0.0
        self.zone2_peak_frame["ws2"] = None
        self.zone2_peak_frame["ds2"] = None

    def _handle_start(self, event_id):
        seq_no = self._alloc_next_seq_no()

        with self._lock:
            self.current_event_id = event_id
            self.current_seq_no = seq_no
            self._reset_zone1()

        img_car = self._save_bgr(self.latest_frames.get("cam1", None), "car", event_id)
        img_ws1 = self._save_bgr(self.latest_frames.get("ws1", None), "ws1_snap", event_id)
        img_ds1 = self._save_bgr(self.latest_frames.get("ds1", None), "ds1_snap", event_id)
        img_ws2 = self._save_bgr(self.latest_frames.get("ws2", None), "ws2_snap", event_id)
        img_ds2 = self._save_bgr(self.latest_frames.get("ds2", None), "ds2_snap", event_id)
        img_w_ws = self._save_bgr(self.latest_frames.get("wheel_ws", None), "wheel_ws", event_id)
        img_w_ds = self._save_bgr(self.latest_frames.get("wheel_ds", None), "wheel_ds", event_id)

        self._emit_patch({
            "event_id": event_id,
            "ts": datetime.now(),
            "seq_no": seq_no,

            "img_car_path": img_car,
            "img_ws1_path": img_ws1,
            "img_ds1_path": img_ds1,
            "img_ws2_path": img_ws2,
            "img_ds2_path": img_ds2,

            "img_ws_wheel_path": img_w_ws,
            "img_ds_wheel_path": img_w_ds,

            "start_done": 1,
            "ui_done": 0,
        })

        try:
            if self.on_set_car_label:
                self.on_set_car_label("START")
        except Exception:
            pass

        if self.snapshot_sec > 0.0:
            try:
                time.sleep(self.snapshot_sec)
            except Exception:
                pass

    def _handle_end(self, event_id):
        eid = str(event_id or "").strip()
        if not eid:
            return

        with self._lock:
            seq_no = int(self.current_seq_no) if self.current_seq_no else 0

            ws1_peak = float(self.zone1_peak.get("ws1", 0.0))
            ds1_peak = float(self.zone1_peak.get("ds1", 0.0))
            ws1_frame = self.zone1_peak_frame.get("ws1", None)
            ds1_frame = self.zone1_peak_frame.get("ds1", None)

            ws2_peak = float(self.zone2_peak.get("ws2", 0.0))
            ds2_peak = float(self.zone2_peak.get("ds2", 0.0))
            ws2_frame = self.zone2_peak_frame.get("ws2", None)
            ds2_frame = self.zone2_peak_frame.get("ds2", None)

            self._reset_zone1()

        img_ws1_peak = self._save_bgr(ws1_frame, "ws1_peak", eid) if ws1_frame is not None else ""
        img_ds1_peak = self._save_bgr(ds1_frame, "ds1_peak", eid) if ds1_frame is not None else ""

        self._emit_patch({
            "event_id": eid,
            "ws1_db": ws1_peak,
            "ds1_db": ds1_peak,
            "img_ws1_path": img_ws1_peak if img_ws1_peak else "",
            "img_ds1_path": img_ds1_peak if img_ds1_peak else "",
            "zone1_done": 1,
        })

        target_eid = ""
        if seq_no > 0:
            target_seq = seq_no - (self.delay_count - 1)
            if target_seq > 0:
                target_eid = self._find_event_id_by_seq_no(target_seq)

        if target_eid:
            img_ws2_peak = self._save_bgr(ws2_frame, "ws2_peak", target_eid) if ws2_frame is not None else ""
            img_ds2_peak = self._save_bgr(ds2_frame, "ds2_peak", target_eid) if ds2_frame is not None else ""

            self._emit_patch({
                "event_id": target_eid,
                "ws2_db": ws2_peak,
                "ds2_db": ds2_peak,
                "img_ws2_path": img_ws2_peak if img_ws2_peak else "",
                "img_ds2_path": img_ds2_peak if img_ds2_peak else "",
                "zone2_done": 1,
            })

        with self._lock:
            self._reset_zone2()
            if self.current_event_id == eid:
                self.current_event_id = ""

    # ------------------------------------------------------------
    # patch emit
    # ------------------------------------------------------------
    def _emit_patch(self, patch):
        if not isinstance(patch, dict):
            return
        try:
            if self.on_stage1_ready:
                self.on_stage1_ready(patch)
        except Exception:
            pass
