import time
from datetime import datetime
import queue as _queue

from PyQt5.QtCore import QThread
import pymysql

from config.config import DB_HOST, DB_PORT, DB_USER, DB_PW

# 고정 DB / TABLE 이름
DB_NAME = "posco"
TABLE_NAME = "data"


class DbWriterThread(QThread):
    """
    큐 item 형식 (대차 1건):

      {
        "ts": datetime,
        "car_no": str,

        "ws1_db": float,
        "ds1_db": float,
        "ws2_db": float,
        "ds2_db": float,

        "img_cam1_path": str,   # 대차번호(AI) 카메라 이미지
        "img_ws1_path": str,
        "img_ds1_path": str,
        "img_ws2_path": str,
        "img_ds2_path": str,

        # ★ 휠 상태 / 이미지 (WS/DS 각각 2개)
        "ws_wheel1_status": str,   # 예: "정상", "비정상", "검출X"
        "ws_wheel2_status": str,
        "ds_wheel1_status": str,
        "ds_wheel2_status": str,
        "img_ws_wheel_path": str,  # WS 휠 이미지 경로
        "img_ds_wheel_path": str,  # DS 휠 이미지 경로
      }

    DB:   posco
    TABLE: data
    """
    def __init__(self, host, port, user, pw, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = int(port)
        self.user = user
        self.pw   = pw

        self.q = _queue.Queue()
        self._running = True

        self._conn = None
        self._conn_dbname = None

    # -------------------------------------------------------------
    # 외부 인터페이스
    # -------------------------------------------------------------
    def stop(self):
        self._running = False
        try:
            self.q.put_nowait(None)
        except Exception:
            pass

    def enqueue(self, item: dict):
        """메인 스레드에서 DB에 넣을 레코드를 큐에 넣을 때 사용"""
        self.q.put(item)

    # -------------------------------------------------------------
    # 내부: 서버 연결 / DB / 테이블 보장
    # -------------------------------------------------------------
    def _connect_server(self):
        """
        서버에 기본 연결 (DB 선택 없이).
        self._conn_dbname == None 상태로 둔다.
        """
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
            cursorclass=pymysql.cursors.DictCursor
        )
        self._conn_dbname = None

    def _ensure_database(self):
        """posco 데이터베이스가 없으면 생성"""
        self._connect_server()
        sql = (
            "CREATE DATABASE IF NOT EXISTS `{}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
        ).format(DB_NAME)
        with self._conn.cursor() as cur:
            cur.execute(sql)

    def _connect_db(self):
        """
        posco DB로 연결.
        """
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
            cursorclass=pymysql.cursors.DictCursor
        )
        self._conn_dbname = DB_NAME

    def _ensure_table(self):
        """
        posco.data 테이블이 없으면 생성.
        (이미 있으면 이 CREATE TABLE은 그냥 패스됨)
        """
        self._ensure_database()
        self._connect_db()

        sql = f"""
        CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
            id BIGINT NOT NULL AUTO_INCREMENT,
            ts DATETIME NOT NULL,
            car_no VARCHAR(32) NOT NULL,

            ws1_db DOUBLE NOT NULL,
            ds1_db DOUBLE NOT NULL,
            ws2_db DOUBLE NOT NULL,
            ds2_db DOUBLE NOT NULL,

            img_car_path  VARCHAR(255) NOT NULL,
            img_ws1_path  VARCHAR(255) NOT NULL,
            img_ds1_path  VARCHAR(255) NOT NULL,
            img_ws2_path  VARCHAR(255) NOT NULL,
            img_ds2_path  VARCHAR(255) NOT NULL,

            -- ★ 휠 상태 4개 + 휠 이미지 2개
            ws_wheel1_status  VARCHAR(32)  NOT NULL,
            ws_wheel2_status  VARCHAR(32)  NOT NULL,
            ds_wheel1_status  VARCHAR(32)  NOT NULL,
            ds_wheel2_status  VARCHAR(32)  NOT NULL,
            img_ws_wheel_path VARCHAR(255) NOT NULL,
            img_ds_wheel_path VARCHAR(255) NOT NULL,

            PRIMARY KEY(id),
            INDEX idx_ts (ts),
            INDEX idx_car (car_no)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        with self._conn.cursor() as cur:
            cur.execute(sql)

    # -------------------------------------------------------------
    # 내부: INSERT
    # -------------------------------------------------------------
    def _insert_row(self, row: dict):
        """
        row 형식은 enqueue로 들어온 dict에서 안전하게 만들어진 값.
        """
        self._ensure_table()

        sql = f"""
        INSERT INTO `{TABLE_NAME}` (
            ts, car_no,
            ws1_db, ds1_db, ws2_db, ds2_db,
            img_car_path, img_ws1_path, img_ds1_path, img_ws2_path, img_ds2_path,
            ws_wheel1_status, ws_wheel2_status, ds_wheel1_status, ds_wheel2_status,
            img_ws_wheel_path, img_ds_wheel_path
        )
        VALUES (%s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s)
        """

        vals = (
            row["ts"],
            row["car_no"],
            row["ws1_db"],
            row["ds1_db"],
            row["ws2_db"],
            row["ds2_db"],
            row["img_car_path"],
            row["img_ws1_path"],
            row["img_ds1_path"],
            row["img_ws2_path"],
            row["img_ds2_path"],
            row["ws_wheel1_status"],
            row["ws_wheel2_status"],
            row["ds_wheel1_status"],
            row["ds_wheel2_status"],
            row["img_ws_wheel_path"],
            row["img_ds_wheel_path"],
        )

        with self._conn.cursor() as cur:
            cur.execute(sql, vals)

    def _process_item(self, item: dict):
        """
        큐에서 꺼낸 raw item(dict)을 안전하게 가공해서 INSERT.
        """
        ts = item.get("ts")
        if not isinstance(ts, datetime):
            ts = datetime.now()

        car_no = (item.get("car_no") or "").strip()

        def _f(key, default=0.0):
            try:
                v = item.get(key, default)
                return float(v)
            except Exception:
                return float(default)

        ws1_db = _f("ws1_db", 0.0)
        ds1_db = _f("ds1_db", 0.0)
        ws2_db = _f("ws2_db", 0.0)
        ds2_db = _f("ds2_db", 0.0)

        def _s(key):
            v = item.get(key, "") or ""
            return str(v)

        # 메인코드에서 img_cam1_path로 전달하는 것을 img_car_path로 매핑
        img_car_path = _s("img_cam1_path")
        img_ws1_path = _s("img_ws1_path")
        img_ds1_path = _s("img_ds1_path")
        img_ws2_path = _s("img_ws2_path")
        img_ds2_path = _s("img_ds2_path")

        # ★ 휠 상태/이미지 (없으면 빈 문자열로 들어감)
        ws_wheel1_status  = _s("ws_wheel1_status")
        ws_wheel2_status  = _s("ws_wheel2_status")
        ds_wheel1_status  = _s("ds_wheel1_status")
        ds_wheel2_status  = _s("ds_wheel2_status")
        img_ws_wheel_path = _s("img_ws_wheel_path")
        img_ds_wheel_path = _s("img_ds_wheel_path")

        row = {
            "ts": ts,
            "car_no": car_no,
            "ws1_db": ws1_db,
            "ds1_db": ds1_db,
            "ws2_db": ws2_db,
            "ds2_db": ds2_db,
            "img_car_path": img_car_path,
            "img_ws1_path": img_ws1_path,
            "img_ds1_path": img_ds1_path,
            "img_ws2_path": img_ws2_path,
            "img_ds2_path": img_ds2_path,
            "ws_wheel1_status": ws_wheel1_status,
            "ws_wheel2_status": ws_wheel2_status,
            "ds_wheel1_status": ds_wheel1_status,
            "ds_wheel2_status": ds_wheel2_status,
            "img_ws_wheel_path": img_ws_wheel_path,
            "img_ds_wheel_path": img_ds_wheel_path,
        }

        self._insert_row(row)

    # -------------------------------------------------------------
    # 스레드 루프
    # -------------------------------------------------------------
    def run(self):
        while self._running:
            try:
                item = self.q.get(timeout=0.5)
            except _queue.Empty:
                continue

            if item is None:
                continue

            try:
                self._process_item(item)
            except Exception as e:
                print("[DB-ERR]", e)
                time.sleep(0.5)
                # 실패한 item은 다시 큐에 넣어 재시도
                try:
                    self.q.put(item)
                except Exception:
                    pass

        # 종료 시 남은 것 처리
        while True:
            try:
                item = self.q.get_nowait()
            except _queue.Empty:
                break

            if item is None:
                continue

            try:
                self._process_item(item)
            except Exception as e:
                print("[DB-ERR-DRAIN]", e)

        # 연결 정리
        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass
