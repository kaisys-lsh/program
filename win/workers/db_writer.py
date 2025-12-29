# workers/db_writer.py
# -*- coding: utf-8 -*-
"""DB Writer Thread

요구사항(2025-12-29)
 - DB가 "큐" 역할을 하도록, item(dict)에 들어온 키만 UPDATE 하는 "부분 patch" 저장을 지원
 - event_id 기준 UPSERT
 - 테이블 컬럼은 NULL 허용(필요한 값이 들어올 때만 채움)
 - HMI 표시는 별도 DB Poller가 done 플래그로 판단
"""

import time
from datetime import datetime
import queue as _queue

from PyQt5.QtCore import QThread
import pymysql


# 고정 DB / TABLE 이름
DB_NAME = "posco"
TABLE_NAME = "data"


class DbWriterThread(QThread):
    """DB Writer

    - enqueue(item): item(dict)에 들어온 키만 DB에 patch(부분 업데이트)
    - event_id를 유일키로 사용
    """

    # 테이블 컬럼(화이트리스트)
    _COL_TYPES = {
        # 기본
        "event_id": "VARCHAR(64) NOT NULL",
        "ts": "DATETIME NULL DEFAULT NULL",
        "car_no": "VARCHAR(32) NULL DEFAULT NULL",

        # 누풍 피크(dB)
        "ws1_db": "DOUBLE NULL DEFAULT NULL",
        "ds1_db": "DOUBLE NULL DEFAULT NULL",
        "ws2_db": "DOUBLE NULL DEFAULT NULL",
        "ds2_db": "DOUBLE NULL DEFAULT NULL",

        # 스냅샷/피크 이미지 경로
        "img_car_path": "VARCHAR(255) NULL DEFAULT NULL",
        "img_ws1_path": "VARCHAR(255) NULL DEFAULT NULL",
        "img_ds1_path": "VARCHAR(255) NULL DEFAULT NULL",
        "img_ws2_path": "VARCHAR(255) NULL DEFAULT NULL",
        "img_ds2_path": "VARCHAR(255) NULL DEFAULT NULL",

        # 휠 상태 + 이미지
        "ws_wheel1_status": "VARCHAR(32) NULL DEFAULT NULL",
        "ws_wheel2_status": "VARCHAR(32) NULL DEFAULT NULL",
        "ds_wheel1_status": "VARCHAR(32) NULL DEFAULT NULL",
        "ds_wheel2_status": "VARCHAR(32) NULL DEFAULT NULL",
        "img_ws_wheel_path": "VARCHAR(255) NULL DEFAULT NULL",
        "img_ds_wheel_path": "VARCHAR(255) NULL DEFAULT NULL",

        # 진행 플래그/판단용
        "seq_no": "BIGINT NOT NULL DEFAULT 0",
        "start_done": "TINYINT NOT NULL DEFAULT 0",
        "car_no_done": "TINYINT NOT NULL DEFAULT 0",
        "zone1_done": "TINYINT NOT NULL DEFAULT 0",
        "zone2_done": "TINYINT NOT NULL DEFAULT 0",
        "wheel_ws_done": "TINYINT NOT NULL DEFAULT 0",
        "wheel_ds_done": "TINYINT NOT NULL DEFAULT 0",
        "ui_done": "TINYINT NOT NULL DEFAULT 0",
    }

    # item -> DB 컬럼 매핑(별칭 처리)
    _ALIASES = {
        "img_cam1_path": "img_car_path",  # 과거 키 호환
        "img_car": "img_car_path",
    }

    def __init__(self, host, port, user, pw, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = int(port)
        self.user = user
        self.pw = pw

        self.q = _queue.Queue()
        self._running = True

        self._conn = None
        self._conn_dbname = None
        self._table_ready = False

    def stop(self):
        self._running = False
        try:
            self.q.put_nowait(None)
        except Exception:
            pass

    def enqueue(self, item: dict):
        if isinstance(item, dict) and "_retry" not in item:
            item["_retry"] = 0
        self.q.put(item)

    # ---------------- DB connect/ensure ----------------
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

        # 1) create table (최초 생성)
        cols_sql = []
        cols_sql.append("id BIGINT NOT NULL AUTO_INCREMENT")
        cols_sql.append("event_id VARCHAR(64) NOT NULL")

        # 나머지 컬럼들
        for k, t in self._COL_TYPES.items():
            if k == "event_id":
                continue
            cols_sql.append(f"`{k}` {t}")

        # 인덱스
        cols_sql.append("PRIMARY KEY(id)")
        cols_sql.append("UNIQUE KEY uq_event (event_id)")
        cols_sql.append("INDEX idx_ts (ts)")
        cols_sql.append("INDEX idx_car (car_no)")
        cols_sql.append(
            "INDEX idx_done (ui_done, start_done, car_no_done, zone1_done, zone2_done, wheel_ws_done, wheel_ds_done)"
        )
        cols_sql_str = ",\n            ".join(cols_sql)

        sql_create = f"""
        CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
            {cols_sql_str}
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """

        with self._conn.cursor() as cur:
            cur.execute(sql_create)

        # 2) 기존 테이블(구버전) 보강: 컬럼 추가/타입 완화(에러 무시)
        def _exec_ignore(sql):
            try:
                with self._conn.cursor() as cur:
                    cur.execute(sql)
            except Exception:
                pass

        # 유니크키 보강
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` ADD UNIQUE KEY uq_event (event_id)")

        # 컬럼 추가
        for col_name, col_type in self._COL_TYPES.items():
            if col_name == "event_id":
                continue
            _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` ADD COLUMN `{col_name}` {col_type}")

        # NOT NULL -> NULL 완화(이미 NOT NULL이면 patch 저장이 막힘)
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN ts DATETIME NULL DEFAULT NULL")
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN car_no VARCHAR(32) NULL DEFAULT NULL")
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN ws1_db DOUBLE NULL DEFAULT NULL")
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN ds1_db DOUBLE NULL DEFAULT NULL")
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN ws2_db DOUBLE NULL DEFAULT NULL")
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN ds2_db DOUBLE NULL DEFAULT NULL")

        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN img_car_path VARCHAR(255) NULL DEFAULT NULL")
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN img_ws1_path VARCHAR(255) NULL DEFAULT NULL")
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN img_ds1_path VARCHAR(255) NULL DEFAULT NULL")
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN img_ws2_path VARCHAR(255) NULL DEFAULT NULL")
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN img_ds2_path VARCHAR(255) NULL DEFAULT NULL")

        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN ws_wheel1_status VARCHAR(32) NULL DEFAULT NULL")
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN ws_wheel2_status VARCHAR(32) NULL DEFAULT NULL")
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN ds_wheel1_status VARCHAR(32) NULL DEFAULT NULL")
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN ds_wheel2_status VARCHAR(32) NULL DEFAULT NULL")
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN img_ws_wheel_path VARCHAR(255) NULL DEFAULT NULL")
        _exec_ignore(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN img_ds_wheel_path VARCHAR(255) NULL DEFAULT NULL")

        self._table_ready = True

    # ---------------- UPSERT (PATCH) ----------------
    def _upsert_patch(self, event_id: str, patch: dict):
        """event_id row에 patch 업데이트

        - patch에 들어온 컬럼만 업데이트
        - ts는 "최초 생성 시간" 용도로 쓰기 위해, 중복 시에는 COALESCE로 유지
        """

        self._ensure_table()

        # 최소 INSERT 보장: ts는 항상 포함(없으면 now)
        if "ts" not in patch:
            patch["ts"] = datetime.now()

        columns = ["event_id"]
        values = [event_id]

        # 컬럼 화이트리스트 순서대로 넣기(안정)
        for col in self._COL_TYPES.keys():
            if col == "event_id":
                continue
            if col in patch:
                columns.append(col)
                values.append(patch[col])

        if len(columns) <= 1:
            # event_id만으로는 INSERT 불가(의미도 없음)
            return

        # INSERT
        col_sql = ", ".join([f"`{c}`" for c in columns])
        placeholders = ", ".join(["%s" for _ in columns])

        # UPDATE
        update_parts = []
        for c in columns:
            if c == "event_id":
                continue
            if c == "ts":
                # ts는 최초값 유지(이미 ts가 있으면 유지)
                update_parts.append("`ts` = COALESCE(`ts`, VALUES(`ts`))")
            else:
                update_parts.append(f"`{c}` = VALUES(`{c}`)")
        update_sql = ", ".join(update_parts)

        sql = (
            f"INSERT INTO `{TABLE_NAME}` ({col_sql}) VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {update_sql}"
        )

        with self._conn.cursor() as cur:
            cur.execute(sql, tuple(values))

    # ---------------- item -> patch ----------------
    def _parse_ts(self, v):
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"]:
                try:
                    return datetime.strptime(s, fmt)
                except Exception:
                    pass
        return None

    def _get_str(self, item, key):
        if key not in item:
            return None
        v = item.get(key)
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        return s

    def _get_int(self, item, key):
        if key not in item:
            return None
        v = item.get(key)
        if v is None:
            return None
        try:
            return int(v)
        except Exception:
            return None

    def _get_float(self, item, key):
        if key not in item:
            return None
        v = item.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except Exception:
            return None

    def _build_patch(self, item: dict):
        patch = {}

        # ts: 있으면 파싱, 없으면 upsert에서 now를 넣음
        if "ts" in item:
            ts = self._parse_ts(item.get("ts"))
            if ts is not None:
                patch["ts"] = ts

        # aliases
        for src, dst in self._ALIASES.items():
            if src in item and dst not in item:
                item[dst] = item.get(src)

        # 문자열 컬럼
        str_cols = [
            "car_no",
            "img_car_path",
            "img_ws1_path",
            "img_ds1_path",
            "img_ws2_path",
            "img_ds2_path",
            "ws_wheel1_status",
            "ws_wheel2_status",
            "ds_wheel1_status",
            "ds_wheel2_status",
            "img_ws_wheel_path",
            "img_ds_wheel_path",
        ]
        for c in str_cols:
            s = self._get_str(item, c)
            if s is not None:
                patch[c] = s

        # 숫자 컬럼
        float_cols = ["ws1_db", "ds1_db", "ws2_db", "ds2_db"]
        for c in float_cols:
            f = self._get_float(item, c)
            if f is not None:
                patch[c] = f

        # 플래그/seq
        int_cols = [
            "seq_no",
            "start_done",
            "car_no_done",
            "zone1_done",
            "zone2_done",
            "wheel_ws_done",
            "wheel_ds_done",
            "ui_done",
        ]
        for c in int_cols:
            iv = self._get_int(item, c)
            if iv is not None:
                patch[c] = iv

        return patch

    def _process_item(self, item: dict):
        # event_id
        event_id = (item.get("event_id") or "").strip()
        if not event_id:
            # event_id는 필수. 없으면 임시로라도 만들어서 저장되게 한다.
            event_id = "noevent-" + datetime.now().strftime("%Y%m%d%H%M%S%f")

        patch = self._build_patch(item)
        self._upsert_patch(event_id, patch)

    def run(self):
        while self._running:
            try:
                item = self.q.get(timeout=0.5)
            except _queue.Empty:
                continue

            if item is None:
                continue

            try:
                if isinstance(item, dict):
                    self._process_item(item)
            except Exception as e:
                print("[DB-ERR]", e)
                retry = 0
                if isinstance(item, dict):
                    try:
                        retry = int(item.get("_retry", 0))
                    except Exception:
                        retry = 0
                retry += 1
                if isinstance(item, dict):
                    item["_retry"] = retry
                time.sleep(0.5)
                if retry <= 10:
                    try:
                        self.q.put(item)
                    except Exception:
                        pass
                else:
                    print("[DB-ERR] drop item (retry limit)")

        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass
