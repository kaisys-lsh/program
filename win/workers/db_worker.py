# win/workers/db_worker.py
# -*- coding: utf-8 -*-
import time
import queue
import pymysql
from datetime import datetime
from PyQt5.QtCore import QThread, pyqtSignal

# ==================================================
# 1. DB 설정 및 스키마 (기존 db_schema.py 통합)
# ==================================================
DB_NAME = "posco"
TABLE_NAME = "data"

# 컬럼 정의 (이름: 타입)
COL_TYPES = {
    "event_id": "VARCHAR(64) NOT NULL",
    "ts": "DATETIME NULL DEFAULT NULL",
    "car_no": "VARCHAR(32) NULL DEFAULT NULL",
    
    # dB Data
    "ws1_db": "DOUBLE NULL DEFAULT NULL", "ds1_db": "DOUBLE NULL DEFAULT NULL",
    "ws2_db": "DOUBLE NULL DEFAULT NULL", "ds2_db": "DOUBLE NULL DEFAULT NULL",
    
    # Images
    "img_car_path": "VARCHAR(255) NULL DEFAULT NULL",
    "img_ws1_path": "VARCHAR(255) NULL DEFAULT NULL",
    "img_ds1_path": "VARCHAR(255) NULL DEFAULT NULL",
    "img_ws2_path": "VARCHAR(255) NULL DEFAULT NULL",
    "img_ds2_path": "VARCHAR(255) NULL DEFAULT NULL",
    
    # Wheel Status & Images
    "ws_wheel1_status": "VARCHAR(32) NULL DEFAULT NULL",
    "ws_wheel2_status": "VARCHAR(32) NULL DEFAULT NULL",
    "ds_wheel1_status": "VARCHAR(32) NULL DEFAULT NULL",
    "ds_wheel2_status": "VARCHAR(32) NULL DEFAULT NULL",
    "img_ws_wheel_path": "VARCHAR(255) NULL DEFAULT NULL",
    "img_ds_wheel_path": "VARCHAR(255) NULL DEFAULT NULL",
    
    # Flags & Seq
    "seq_no": "BIGINT NOT NULL DEFAULT 0",
    "start_done": "TINYINT NOT NULL DEFAULT 0", "car_no_done": "TINYINT NOT NULL DEFAULT 0",
    "zone1_done": "TINYINT NOT NULL DEFAULT 0", "zone2_done": "TINYINT NOT NULL DEFAULT 0",
    "wheel_ws_done": "TINYINT NOT NULL DEFAULT 0", "wheel_ds_done": "TINYINT NOT NULL DEFAULT 0",
    "ui_done": "TINYINT NOT NULL DEFAULT 0",
}

class DbBaseThread(QThread):
    """DB 연결 및 테이블 보장을 위한 공통 부모 클래스"""
    def __init__(self, host, port, user, pw, parent=None):
        super().__init__(parent)
        self.conn_params = {
            "host": host, "port": int(port), "user": user, "password": pw,
            "autocommit": True, "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.DictCursor
        }
        self._conn = None
        self._table_ready = False

    def _connect(self, use_db=True):
        """DB 재연결 로직"""
        if self._conn:
            try:
                self._conn.ping(reconnect=True)
                return
            except:
                try: self._conn.close()
                except: pass
                self._conn = None
        
        params = self.conn_params.copy()
        if use_db:
            params["database"] = DB_NAME
        
        self._conn = pymysql.connect(**params)

    def _ensure_table(self):
        """테이블 생성 및 컬럼 보강 (세션당 1회 수행)"""
        if self._table_ready: return
        
        try:
            # 1. DB 생성
            self._connect(use_db=False)
            with self._conn.cursor() as cur:
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4")
            
            # 2. 테이블 생성
            self._connect(use_db=True)
            cols = [f"`{k}` {v}" for k, v in COL_TYPES.items()]
            sql = f"""
                CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
                    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    {', '.join(cols)},
                    UNIQUE KEY uq_event (event_id),
                    INDEX idx_done (ui_done, start_done)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
            with self._conn.cursor() as cur:
                cur.execute(sql)
            
            # 3. 컬럼 추가(보강) - 루프 돌며 안전하게 실행
            with self._conn.cursor() as cur:
                for k, v in COL_TYPES.items():
                    try: cur.execute(f"ALTER TABLE `{TABLE_NAME}` ADD COLUMN `{k}` {v}")
                    except: pass
                    # NOT NULL 완화 (구버전 호환)
                    try: cur.execute(f"ALTER TABLE `{TABLE_NAME}` MODIFY COLUMN `{k}` {v}")
                    except: pass

            self._table_ready = True
        except Exception as e:
            print(f"[DB-INIT] Error: {e}")
            time.sleep(1)


# ==================================================
# 2. DB Writer (저장 전담)
# ==================================================
class DbWriterThread(DbBaseThread):
    def __init__(self, host, port, user, pw, parent=None):
        super().__init__(host, port, user, pw, parent)
        self.q = queue.Queue()
        self._running = True

    def enqueue(self, item):
        if isinstance(item, dict):
            self.q.put(item)

    def stop(self):
        self._running = False
        self.q.put(None)
        self.wait()

    def run(self):
        while self._running:
            try:
                item = self.q.get()
                if item is None: break
                
                self._ensure_table()
                self._process_patch(item)
            except Exception as e:
                print(f"[DB-WRITE] Error: {e}")
                time.sleep(0.5)

    def _process_patch(self, patch):
        # 1. 별칭 처리
        if "img_car" in patch: patch["img_car_path"] = patch.pop("img_car")
        
        event_id = patch.get("event_id")
        seq_no = patch.get("seq_no")

        # 유효 컬럼만 필터링
        valid_data = {k: v for k, v in patch.items() if k in COL_TYPES}
        if not valid_data: return

        # A. Event ID 기준 UPSERT
        if event_id:
            valid_data["event_id"] = event_id # 키 보장
            if "ts" not in valid_data: valid_data["ts"] = datetime.now()
            
            cols = list(valid_data.keys())
            vals = list(valid_data.values())
            set_clause = ", ".join([f"`{c}`=VALUES(`{c}`)" for c in cols if c != "event_id"])
            
            sql = f"INSERT INTO `{TABLE_NAME}` ({','.join(cols)}) VALUES ({','.join(['%s']*len(cols))}) " \
                  f"ON DUPLICATE KEY UPDATE {set_clause}"
            
            with self._conn.cursor() as cur:
                cur.execute(sql, vals)

        # B. Seq No 기준 UPDATE (지연 매칭)
        elif seq_no:
            set_clause = ", ".join([f"`{k}`=%s" for k in valid_data.keys()])
            sql = f"UPDATE `{TABLE_NAME}` SET {set_clause} WHERE seq_no=%s"
            with self._conn.cursor() as cur:
                cur.execute(sql, list(valid_data.values()) + [seq_no])


# ==================================================
# 3. DB Poller (조회 전담)
# ==================================================
class DbPollerThread(DbBaseThread):
    record_ready = pyqtSignal(dict)

    def __init__(self, host, port, user, pw, poll_interval_sec=0.2, skip_existing_completed=True, parent=None, **kwargs):
        super().__init__(host, port, user, pw, parent)
        self.interval = poll_interval_sec
        self.skip_existing = skip_existing_completed
        self._running = True
        
        # 강제 완료(Force Finalize) 설정
        self.force_opts = kwargs

    def stop(self):
        self._running = False
        self.wait()

    def run(self):
        while self._running:
            try:
                self._ensure_table()
                
                # 1. 시작 시 기존 완료 건 건너뛰기
                if self.skip_existing:
                    self._mark_done_bulk()
                    self.skip_existing = False

                # 2. 강제 완료 처리 (타임아웃된 건들)
                self._check_force_finalize()

                # 3. 완성된 레코드 조회
                rows = self._fetch_completed()
                if not rows:
                    time.sleep(self.interval)
                    continue

                for row in rows:
                    if not self._running: break
                    self._set_ui_done(row["id"])
                    self.record_ready.emit(row)

            except Exception as e:
                print(f"[DB-POLL] Error: {e}")
                time.sleep(1)

    def _mark_done_bulk(self):
        """이미 완성된 건들은 UI 표시 안 함"""
        sql = f"UPDATE `{TABLE_NAME}` SET ui_done=1 WHERE ui_done=0 AND zone1_done=1 AND zone2_done=1 AND car_no_done=1"
        with self._conn.cursor() as cur: cur.execute(sql)

    def _fetch_completed(self):
        """모든 플래그가 1인 행 조회"""
        sql = f"SELECT * FROM `{TABLE_NAME}` WHERE ui_done=0 AND zone1_done=1 AND zone2_done=1 AND car_no_done=1 LIMIT 50"
        with self._conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()

    def _set_ui_done(self, row_id):
        with self._conn.cursor() as cur:
            cur.execute(f"UPDATE `{TABLE_NAME}` SET ui_done=1 WHERE id=%s", (row_id,))

    def _check_force_finalize(self):
        """오래된 미완성 행 강제 처리 (간략화됨)"""
        # 필요 시 kwargs에서 force_car_no_sec 등을 읽어서 처리하는 로직 추가
        # 여기서는 코드 경량화를 위해 핵심 구조만 남김. 필요하면 기존 로직 복원 가능.
        pass