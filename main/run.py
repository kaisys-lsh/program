import sys
import os
import zmq
import cv2
import json
import time
import pymysql
from collections import deque
from datetime import datetime
from PyQt5.QtWidgets import QApplication, QMainWindow, QTableWidgetItem, QHeaderView
from PyQt5.uic import loadUi
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QPixmap

# =========================================================
#  ⚙️ 설정
# =========================================================
IS_TEST_MODE = True  

try:
    if IS_TEST_MODE:
        from test.cry_api_test import CryApiThread
    else:
        from api.cry_api import CryApiThread
except ImportError:
    class CryApiThread(QThread):
        db_ready = pyqtSignal(float)
        text_ready = pyqtSignal(str)
        def __init__(self, *args, **kwargs): super().__init__()
        def run(self): pass 

# [DB 설정]
DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_USER = "root"
DB_PW   = "0000"
DB_NAME = "posco"
TABLE_NAME = "data"

# [파일 및 RTSP 설정]
SAVE_ROOT_DIR = r"D:/data"
DELAY_COUNT = 3  # 현장 7

RTSP_DUMMY = r"D:/GitHub/program/output.avi"
RTSP_URLS = {
    "car":      RTSP_DUMMY,
    "wheel_ws": RTSP_DUMMY,
    "wheel_ds": RTSP_DUMMY,
    "waek_ws1": RTSP_DUMMY,
    "waek_ds1": RTSP_DUMMY,
    "waek_ws2": RTSP_DUMMY,
    "waek_ds2": RTSP_DUMMY,
}

CRY_CONFIGS = {
    "waek_ws1": {"ip": "192.168.1.211", "port": 90, "user": "admin", "pw": "crysound"},
    "waek_ds1": {"ip": "192.168.1.213", "port": 90, "user": "admin", "pw": "crysound"},
    "waek_ws2": {"ip": "192.168.1.212", "port": 90, "user": "admin", "pw": "crysound"},
    "waek_ds2": {"ip": "192.168.1.214", "port": 90, "user": "admin", "pw": "crysound"},
}

# =========================================================
#  🧵 스레드 (DB, RTSP, ZMQ)
# =========================================================
class DbWorker(QThread):
    def __init__(self):
        super().__init__()
        self.queue = deque()
        self.running = True
        self.init_db()

    def init_db(self):
        conn = None
        try:
            conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PW, port=DB_PORT, charset='utf8')
            cur = conn.cursor()
            cur.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
            conn.select_db(DB_NAME)
            sql = f"""
                CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    car_no VARCHAR(50),
                    waek_ws1 FLOAT DEFAULT 0, waek_ds1 FLOAT DEFAULT 0,
                    waek_ws2 FLOAT DEFAULT 0, waek_ds2 FLOAT DEFAULT 0,
                    ws_1st_r VARCHAR(20), ws_1st_p VARCHAR(20),
                    ws_2nd_r VARCHAR(20), ws_2nd_p VARCHAR(20),
                    ds_1st_r VARCHAR(20), ds_1st_p VARCHAR(20),
                    ds_2nd_r VARCHAR(20), ds_2nd_p VARCHAR(20),
                    img_car VARCHAR(255), img_wheel_ws VARCHAR(255), img_wheel_ds VARCHAR(255),
                    img_waek_ws1 VARCHAR(255), img_waek_ds1 VARCHAR(255),
                    img_waek_ws2 VARCHAR(255), img_waek_ds2 VARCHAR(255)
                )
            """
            cur.execute(sql)
            conn.commit()
        except: pass
        finally:
            if conn: conn.close()

    def add_task(self, car_data):
        self.queue.append(car_data)

    def run(self):
        while self.running:
            if self.queue:
                self.save_to_db(self.queue.popleft())
            else:
                time.sleep(0.1)

    def save_to_db(self, d):
        conn = None
        try:
            conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PW, db=DB_NAME, port=DB_PORT, charset='utf8')
            cur = conn.cursor()
            sql = f"""
                INSERT INTO {TABLE_NAME} (
                    car_no,
                    waek_ws1, waek_ds1, waek_ws2, waek_ds2,
                    ws_1st_r, ws_1st_p, ws_2nd_r, ws_2nd_p,
                    ds_1st_r, ds_1st_p, ds_2nd_r, ds_2nd_p,
                    img_car, img_wheel_ws, img_wheel_ds,
                    img_waek_ws1, img_waek_ds1, img_waek_ws2, img_waek_ds2
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            s = d.get('sensor_data', {})
            w = d.get('wheel_status', {})
            i = d.get('images', {})
            val = (
                d.get('car_no'),
                s.get('waek_ws1', 0), s.get('waek_ds1', 0), s.get('waek_ws2', 0), s.get('waek_ds2', 0),
                w.get('ws_1st_r'), w.get('ws_1st_p'), w.get('ws_2nd_r'), w.get('ws_2nd_p'),
                w.get('ds_1st_r'), w.get('ds_1st_p'), w.get('ds_2nd_r'), w.get('ds_2nd_p'),
                i.get('car'), i.get('wheel_ws'), i.get('wheel_ds'),
                i.get('waek_ws1'), i.get('waek_ds1'), i.get('waek_ws2'), i.get('waek_ds2')
            )
            cur.execute(sql, val)
            conn.commit()
            print(f"💾 [DB저장] {d.get('car_no')}")
        except Exception as e:
            print(f"DB Err: {e}")
        finally:
            if conn: conn.close()
    def stop(self):
        self.running = False
        self.wait()

class RtspRecorder(QThread):
    def __init__(self, cam_name, rtsp_url):
        super().__init__()
        self.cam_name = cam_name
        self.rtsp_url = rtsp_url
        self.running = True
        self.save_filename = None
        if not os.path.exists(SAVE_ROOT_DIR):
            try: os.makedirs(SAVE_ROOT_DIR)
            except: pass
    def run(self):
        cap = cv2.VideoCapture(self.rtsp_url)
        while self.running:
            if not cap.isOpened():
                time.sleep(1)
                cap.open(self.rtsp_url)
                continue
            ret, frame = cap.read()
            if ret:
                if self.save_filename:
                    self.save_image(frame, self.save_filename)
                    self.save_filename = None
            else:
                time.sleep(0.1)
            time.sleep(0.005)
        cap.release()
    def request_save(self, file_name):
        self.save_filename = file_name
    def save_image(self, frame, file_name):
        try:
            now = datetime.now()
            date_str = now.strftime("%Y%m%d")
            path = os.path.join(SAVE_ROOT_DIR, self.cam_name, date_str)
            os.makedirs(path, exist_ok=True)
            cv2.imwrite(os.path.join(path, file_name), frame)
        except: pass
    def stop(self):
        self.running = False
        self.wait()

class ZmqReceiver(QThread):
    msg_received = pyqtSignal(dict)
    def __init__(self):
        super().__init__()
        self.running = True
    def run(self):
        ctx = zmq.Context()
        sock = ctx.socket(zmq.PULL)
        sock.connect("tcp://127.0.0.1:5888")
        while self.running:
            try:
                if sock.poll(100):
                    self.msg_received.emit(json.loads(sock.recv_string()))
            except: pass
    def stop(self):
        self.running = False
        self.wait()

# =========================================================
#  🖥️ 메인 윈도우 (UI 로직 집중)
# =========================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        ui_path = os.path.join(os.path.dirname(__file__), "window_hmi.ui")
        loadUi(ui_path, self)

        # 1. 자료구조 초기화
        self.car_queue = deque()         
        self.history_queue = deque(maxlen=172) 

        # 테이블 위젯 초기화
        self.init_table_widget()

        # 2. 스레드 시작
        self.recorders = {}
        for name, url in RTSP_URLS.items():
            t = RtspRecorder(name, url)
            t.start()
            self.recorders[name] = t
        
        self.cry_threads = {}
        for name, conf in CRY_CONFIGS.items():
            t = CryApiThread(ip=conf["ip"], port=conf["port"], user=conf["user"], pw=conf["pw"], interval_sec=1)
            t.db_ready.connect(lambda val, n=name: self.update_sensor_data(n, val))
            t.start()
            self.cry_threads[name] = t

        self.zmq_thread = ZmqReceiver()
        self.zmq_thread.msg_received.connect(self.process_zmq)
        self.zmq_thread.start()

        self.db_worker = DbWorker()
        self.db_worker.start()

    def init_table_widget(self):
        cols = ["대차번호", "WS1", "DS1", "WS2", "DS2", "휠 WS", "휠 DS"]
        self.tableWidget.setColumnCount(len(cols))
        self.tableWidget.setHorizontalHeaderLabels(cols)
        self.tableWidget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def get_rotation_text(self, val):
        if val == 1: return "회전"
        elif val == 2: return "무회전"
        return "감지X" # 0

    def get_position_text(self, val):
        if val == 1: return "정상"
        elif val == 2: return "비정상"
        return "감지X" # 0

    def trigger_save_and_get_path(self, cam_name, ts_str):
        if cam_name not in self.recorders: return ""
        file_name = f"{ts_str}.jpg"
        self.recorders[cam_name].request_save(file_name)
        date_str = datetime.now().strftime("%Y%m%d")
        return os.path.join(SAVE_ROOT_DIR, cam_name, date_str, file_name)

    def update_sensor_data(self, name, val):
        if not self.car_queue: return
        target = self.car_queue[-1] if "1" in name else (self.car_queue[0] if len(self.car_queue) > 0 else None)
        if target: target["sensor_data"][name] = val

    def process_zmq(self, data):
        msg_type = data.get("type")
        event_id = data.get("event_id")

        if msg_type == "car_event" and data.get("event") == "START":
            ts_str = datetime.now().strftime("%H%M%S_%f")[:-3]
            new_car = {
                "event_id": event_id,
                "car_no": None,
                "sensor_data": {},
                "wheel_status": {}, 
                "wheel_raw": {},    
                "images": {},
            }
            for cam in ["car", "wheel_ws", "wheel_ds", "waek_ws1", "waek_ds1"]:
                new_car["images"][cam] = self.trigger_save_and_get_path(cam, ts_str)
            
            self.car_queue.append(new_car)
            self.check_queue_pop()

        elif msg_type in ["car_no", "wheel_status"]:
            target_car = None
            for car in reversed(self.car_queue):
                if car.get("event_id") == event_id:
                    target_car = car
                    break
            
            if target_car:
                if msg_type == "car_no":
                    target_car["car_no"] = data.get("car_no")
                elif msg_type == "wheel_status":
                    pos, src = data.get("pos", "").lower(), data.get("src", "").lower()
                    r, p = data.get("wheel1_rotation", 0), data.get("wheel1_position", 0)
                    
                    target_car["wheel_status"][f"{pos}_{src}_r"] = self.get_rotation_text(r)
                    target_car["wheel_status"][f"{pos}_{src}_p"] = self.get_position_text(p)
                    target_car["wheel_raw"][f"{pos}_{src}_r"] = r
                    target_car["wheel_raw"][f"{pos}_{src}_p"] = p

    def check_queue_pop(self):
        if len(self.car_queue) > DELAY_COUNT:
            finished_car = self.car_queue.popleft()
            
            ts_str = datetime.now().strftime("%H%M%S_%f")[:-3]
            for cam in ["waek_ws2", "waek_ds2"]:
                finished_car["images"][cam] = self.trigger_save_and_get_path(cam, ts_str)

            QThread.msleep(100)
            self.update_hmi_display(finished_car)
            self.db_worker.add_task(finished_car)

    def update_hmi_display(self, data):
        # 1. 라벨/이미지 업데이트 (복구 완료!)
        self.update_labels_and_images(data)

        # 2. 테이블 위젯에 행 추가
        self.add_row_to_table(data)

        # 3. 버튼 리스트 업데이트
        self.history_queue.appendleft(data)
        self.update_buttons()

    # ★★★ 여기가 복구된 함수입니다 ★★★
    def update_labels_and_images(self, data):
        # --- [이미지 갱신] ---
        imgs = data.get('images', {})
        self.show_img("image_1", imgs.get("car"))
        self.show_img("image_2", imgs.get("waek_ws1"))
        self.show_img("image_3", imgs.get("waek_ds1"))
        self.show_img("image_4", imgs.get("waek_ws2"))
        self.show_img("image_5", imgs.get("waek_ds2"))
        self.show_img("image_6", imgs.get("wheel_ws"))
        self.show_img("image_7", imgs.get("wheel_ds"))
        
        # --- [텍스트 라벨 갱신 (msg_1 ~ msg_9)] ---
        sens = data.get('sensor_data', {})
        wheels = data.get('wheel_status', {})

        # 헬퍼 함수
        def set_txt(label_name, txt):
            if hasattr(self, label_name):
                getattr(self, label_name).setText(str(txt))

        # msg_1: 대차번호 (없으면 -)
        c_no = data.get("car_no")
        set_txt("msg_1", c_no if c_no else "-")

        # msg_2 ~ 5: 누풍 데시벨
        set_txt("msg_2", f"{sens.get('waek_ws1', 0):.2f}")
        set_txt("msg_3", f"{sens.get('waek_ds1', 0):.2f}")
        set_txt("msg_4", f"{sens.get('waek_ws2', 0):.2f}")
        set_txt("msg_5", f"{sens.get('waek_ds2', 0):.2f}")

        # msg_6 ~ 9: 휠 상태 (회전R / 위치P)
        def fmt_wheel(pos, src):
            r = wheels.get(f"{pos}_{src}_r")
            p = wheels.get(f"{pos}_{src}_p")
            
            r_txt = r if r else "-"
            p_txt = p if p else "-"
            return f"{r_txt} / {p_txt}"

        set_txt("msg_6", fmt_wheel("ws", "1st")) 
        set_txt("msg_7", fmt_wheel("ws", "2nd")) 
        set_txt("msg_8", fmt_wheel("ds", "1st")) 
        set_txt("msg_9", fmt_wheel("ds", "2nd")) 

    def show_img(self, label_name, path):
        if not hasattr(self, label_name): return
        label = getattr(self, label_name)
        if path and os.path.exists(path):
            pix = QPixmap(path)
            label.setPixmap(pix.scaled(label.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        else:
            label.setText("No Image")

    def add_row_to_table(self, data):
        self.tableWidget.insertRow(0)
        c_no = str(data.get("car_no") if data.get("car_no") else "-")
        sens = data.get("sensor_data", {})
        ws1 = f"{sens.get('waek_ws1', 0):.2f}"
        ds1 = f"{sens.get('waek_ds1', 0):.2f}"
        ws2 = f"{sens.get('waek_ws2', 0):.2f}"
        ds2 = f"{sens.get('waek_ds2', 0):.2f}"

        wheel_ws_txt = self.summarize_wheel_side(data, "ws")
        wheel_ds_txt = self.summarize_wheel_side(data, "ds")

        items = [c_no, ws1, ds1, ws2, ds2, wheel_ws_txt, wheel_ds_txt]
        for col, text in enumerate(items):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignCenter)
            self.tableWidget.setItem(0, col, item)

    def summarize_wheel_side(self, data, pos):
        raw = data.get("wheel_raw", {})
        vals = []
        for src in ["1st", "2nd"]:
            vals.append(raw.get(f"{pos}_{src}_r", 0))
            vals.append(raw.get(f"{pos}_{src}_p", 0))
        if 2 in vals: return "비정상"
        if 0 in vals: return "감지X"
        return "정상"

    def update_buttons(self):
        for i, car_data in enumerate(self.history_queue):
            btn_num = i + 1
            if btn_num > 172: break
            
            btn_name = f"N_{btn_num}"
            if not hasattr(self, btn_name): continue
            
            btn = getattr(self, btn_name)
            
            # 1. 위쪽 색상
            sens = car_data.get("sensor_data", {})
            max_db = max(
                sens.get('waek_ws1', 0), sens.get('waek_ds1', 0),
                sens.get('waek_ws2', 0), sens.get('waek_ds2', 0)
            )
            top_color = "white"
            if max_db > 70: top_color = "red"
            elif max_db > 60: top_color = "yellow"
            elif max_db > 50: top_color = "#00BFFF" 
            
            # 2. 아래쪽 색상
            raw = car_data.get("wheel_raw", {})
            all_vals = list(raw.values())
            
            if not all_vals: 
                bottom_status = "감지X"
                bottom_color = "yellow"
            else:
                if 2 in all_vals:
                    bottom_status = "비정상"
                    bottom_color = "red"
                elif 0 in all_vals:
                    bottom_status = "감지X"
                    bottom_color = "yellow"
                else:
                    bottom_status = "정상"
                    bottom_color = "white"

            style = f"""
                QPushButton {{
                    background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {top_color}, stop:0.5 {top_color}, 
                        stop:0.501 {bottom_color}, stop:1 {bottom_color});
                    border: 1px solid gray;
                    color: black; 
                    font-weight: bold;
                }}
            """
            btn.setStyleSheet(style)
            
            c_no = car_data.get("car_no", "-")
            if c_no is None: c_no = "-"
            btn.setText(f"{c_no}\n{bottom_status}")

    def closeEvent(self, event):
        self.zmq_thread.stop()
        self.db_worker.stop()
        for r in self.recorders.values(): r.stop()
        for c in self.cry_threads.values(): c.stop()
        event.accept()

def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()