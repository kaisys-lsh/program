# workers/db_poller.py
# -*- coding: utf-8 -*-
import time
from datetime import datetime

import pymysql
from PyQt5.QtCore import QThread, pyqtSignal

DB_NAME = "posco"
TABLE_NAME = "data"


class DbPollerThread(QThread):
    record_ready = pyqtSignal(dict)

    # db_writer.py 와 동일한 스키마(최소 일치 보장)
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
        host,
        port,
        user,
        pw,
        poll_interval_sec=0.2,
        skip_existing_completed=True,

        enable_force_finalize=True,
        force_car_no_sec=5.0,
        force_wheel_sec=5.0,
        force_zone1_sec=5.0,
        force_zone2_sec=None,

        parent=None
    ):
        super().__init__(parent)
        self.host = host
        self.port = int(port)
        self.user = user
        self.pw = pw

        try:
            self.poll_interval_sec = float(poll_interval_sec)
        except Exception:
            self.poll_interval_sec = 0.2

        self.skip_existing_completed = bool(skip_existing_completed)

        self.enable_force_finalize = bool(enable_force_finalize)
        self.force_car_no_sec = float(force_car_no_sec) if force_car_no_sec is not None else None
        self.force_wheel_sec = float(force_wheel_sec) if force_wheel_sec is not None else None
        self.force_zone1_sec = float(force_zone1_sec) if force_zone1_sec is not None else None
        self.force_zone2_sec = float(force_zone2_sec) if force_zone2_sec is not None else None

        self._running = True
        self._conn = None
        self._conn_dbname = None
        self._table_ready = False

        self._finalize_last_ts = 0.0
        self._finalize_interval_sec = 0.5

    def stop(self):
        self._running = False

    # ---------------------------------------------------------
    # DB / TABLE ensure (테이블 없으면 자동 생성 + 컬럼 보강)
    # ---------------------------------------------------------
    def _connect_server(self):
        if self._conn is not None and self._conn_dbname is None:
            try:
                self._conn.ping(reconnect=True)
                return
            except Exception:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

        self._conn = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.pw,
            autocommit=True,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        self._conn_dbname = None

    def _ensure_database(self):
        self._connect_server()
        sql = (
            "CREATE DATABASE IF NOT EXISTS `{}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
        ).format(DB_NAME)
        with self._conn.cursor() as cur:
            cur.execute(sql)

    def _connect_db(self):
        if self._conn is not None and self._conn_dbname == DB_NAME:
            try:
                self._conn.ping(reconnect=True)
                return
            except Exception:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

        self._conn = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.pw,
            database=DB_NAME,
            autocommit=True,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        self._conn_dbname = DB_NAME

    def _ensure_table(self):
        if self._table_ready:
            return

        self._ensure_database()
        self._connect_db()

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
        cols_sql.append(
            "INDEX idx_done (ui_done, start_done, car_no_done, zone1_done, zone2_done, wheel_ws_done, wheel_ds_done)"
        )

        sql_create = f"""
        CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
            {", ".join(cols_sql)}
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """

        with self._conn.cursor() as cur:
            cur.execute(sql_create)

        def _exec_ignore(sql):
            try:
                with self._conn.cursor() as cur:
                    cur.execute(sql)
            except Exception:
                pass

        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` ADD UNIQUE KEY uq_event (event_id)")

        for col_name, col_type in self._COL_TYPES.items():
            if col_name == "event_id":
                continue
            _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` ADD COLUMN `{col_name}` {col_type}")

        # NOT NULL -> NULL 완화(구버전 방어)
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN ts DATETIME NULL DEFAULT NULL")
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN car_no VARCHAR(32) NULL DEFAULT NULL")

        self._table_ready = True

    # ---------------------------------------------------------
    # Query helpers
    # ---------------------------------------------------------
    def _mark_existing_completed_as_done(self):
        sql = f"""
        UPDATE `{TABLE_NAME}`
        SET ui_done=1
        WHERE ui_done=0
          AND start_done=1
          AND car_no_done=1
          AND zone1_done=1
          AND zone2_done=1
          AND wheel_ws_done=1
          AND wheel_ds_done=1
        """
        with self._conn.cursor() as cur:
            cur.execute(sql)

    def _fetch_completed_rows(self, limit_n=50):
        sql = f"""
        SELECT *
        FROM `{TABLE_NAME}`
        WHERE ui_done=0
          AND start_done=1
          AND car_no_done=1
          AND zone1_done=1
          AND zone2_done=1
          AND wheel_ws_done=1
          AND wheel_ds_done=1
        ORDER BY id ASC
        LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (int(limit_n),))
            return cur.fetchall()

    def _set_ui_done(self, row_id):
        sql = f"UPDATE `{TABLE_NAME}` SET ui_done=1 WHERE id=%s"
        with self._conn.cursor() as cur:
            cur.execute(sql, (int(row_id),))

    def _normalize_record(self, r: dict):
        rec = dict(r)

        ts = rec.get("ts")
        if isinstance(ts, datetime):
            rec["ts"] = ts.strftime("%Y-%m-%d %H:%M:%S")
        else:
            rec["ts"] = str(ts) if ts is not None else ""

        for k in ("ws1_db", "ds1_db", "ws2_db", "ds2_db"):
            try:
                v = rec.get(k, 0.0)
                if v is None:
                    v = 0.0
                rec[k] = float(v)
            except Exception:
                rec[k] = 0.0

        for k in (
            "event_id", "car_no",
            "img_car_path", "img_ws1_path", "img_ds1_path", "img_ws2_path", "img_ds2_path",
            "img_ws_wheel_path", "img_ds_wheel_path",
            "ws_wheel1_status", "ws_wheel2_status", "ds_wheel1_status", "ds_wheel2_status",
        ):
            v = rec.get(k, "")
            rec[k] = str(v) if v is not None else ""

        return rec

    # ---------------------------------------------------------
    # Force finalize (미완성 영원 방지)
    # ---------------------------------------------------------
    def _fetch_incomplete_rows_older_than(self, age_sec, limit_n=200):
        sql = f"""
        SELECT id, event_id, ts,
               car_no_done, zone1_done, zone2_done, wheel_ws_done, wheel_ds_done,
               car_no,
               ws1_db, ds1_db, ws2_db, ds2_db,
               ws_wheel1_status, ws_wheel2_status, ds_wheel1_status, ds_wheel2_status
        FROM `{TABLE_NAME}`
        WHERE ui_done=0
          AND start_done=1
          AND (
                car_no_done=0
             OR zone1_done=0
             OR zone2_done=0
             OR wheel_ws_done=0
             OR wheel_ds_done=0
          )
          AND ts IS NOT NULL
          AND TIMESTAMPDIFF(SECOND, ts, NOW()) >= %s
        ORDER BY id ASC
        LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (int(age_sec), int(limit_n)))
            return cur.fetchall()

    def _force_update_patch_by_id(self, row_id, patch: dict):
        if row_id is None or not isinstance(patch, dict) or len(patch) == 0:
            return

        set_sql = []
        vals = []
        for k in patch.keys():
            set_sql.append(f"`{k}`=%s")
            vals.append(patch.get(k))

        sql = f"UPDATE `{TABLE_NAME}` SET {', '.join(set_sql)} WHERE id=%s"
        vals.append(int(row_id))

        with self._conn.cursor() as cur:
            cur.execute(sql, tuple(vals))

    def _age_seconds(self, ts):
        if not isinstance(ts, datetime):
            return 0.0
        now = datetime.now()
        return float((now - ts).total_seconds())

    def _force_finalize_incomplete_rows(self):
        if not self.enable_force_finalize:
            return

        now_t = time.time()
        if (now_t - self._finalize_last_ts) < self._finalize_interval_sec:
            return
        self._finalize_last_ts = now_t

        min_sec = None
        for v in (self.force_car_no_sec, self.force_wheel_sec, self.force_zone1_sec, self.force_zone2_sec):
            if v is None:
                continue
            if min_sec is None or v < min_sec:
                min_sec = v
        if min_sec is None:
            return

        rows = self._fetch_incomplete_rows_older_than(age_sec=min_sec, limit_n=200)
        if not rows:
            return

        for r in rows:
            row_id = r.get("id")
            ts = r.get("ts")
            age = self._age_seconds(ts)

            patch = {}

            if r.get("car_no_done", 0) == 0 and self.force_car_no_sec is not None and age >= self.force_car_no_sec:
                if not r.get("car_no"):
                    patch["car_no"] = "NONE"
                patch["car_no_done"] = 1

            if r.get("zone1_done", 0) == 0 and self.force_zone1_sec is not None and age >= self.force_zone1_sec:
                if r.get("ws1_db") is None:
                    patch["ws1_db"] = 0.0
                if r.get("ds1_db") is None:
                    patch["ds1_db"] = 0.0
                patch["zone1_done"] = 1

            if r.get("wheel_ws_done", 0) == 0 and self.force_wheel_sec is not None and age >= self.force_wheel_sec:
                if not r.get("ws_wheel1_status"):
                    patch["ws_wheel1_status"] = "NO_DATA"
                if not r.get("ws_wheel2_status"):
                    patch["ws_wheel2_status"] = "NO_DATA"
                patch["wheel_ws_done"] = 1

            if r.get("wheel_ds_done", 0) == 0 and self.force_wheel_sec is not None and age >= self.force_wheel_sec:
                if not r.get("ds_wheel1_status"):
                    patch["ds_wheel1_status"] = "NO_DATA"
                if not r.get("ds_wheel2_status"):
                    patch["ds_wheel2_status"] = "NO_DATA"
                patch["wheel_ds_done"] = 1

            if r.get("zone2_done", 0) == 0 and self.force_zone2_sec is not None and age >= self.force_zone2_sec:
                if r.get("ws2_db") is None:
                    patch["ws2_db"] = 0.0
                if r.get("ds2_db") is None:
                    patch["ds2_db"] = 0.0
                patch["zone2_done"] = 1

            if patch:
                try:
                    self._force_update_patch_by_id(row_id, patch)
                except Exception as e:
                    print("[DB-FINALIZE-ERR]", e)

    # ---------------------------------------------------------
    # main loop
    # ---------------------------------------------------------
    def run(self):
        while self._running:
            try:
                # ✅ 여기서 DB/테이블을 항상 보장
                self._ensure_table()

                if self.skip_existing_completed:
                    self._mark_existing_completed_as_done()
                    self.skip_existing_completed = False

                self._force_finalize_incomplete_rows()

                rows = self._fetch_completed_rows(limit_n=50)
                if not rows:
                    time.sleep(self.poll_interval_sec)
                    continue

                for r in rows:
                    if not self._running:
                        break

                    row_id = r.get("id")
                    if row_id is None:
                        continue

                    self._set_ui_done(row_id)

                    rec = self._normalize_record(r)
                    try:
                        self.record_ready.emit(rec)
                    except Exception:
                        pass

            except Exception as e:
                print("[DB-POLLER-ERR]", e)
                time.sleep(0.8)

        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass
