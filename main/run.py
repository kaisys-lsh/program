import sys
import os
import zmq
import cv2
import json
import time
import pymysql
import subprocess  # [중요] 외부 뷰어 프로그램 실행을 위해 필요
from collections import deque
from datetime import datetime
from PyQt5.QtWidgets import QApplication, QMainWindow, QTableWidgetItem, QHeaderView, QMessageBox, QPushButton
from PyQt5.uic import loadUi
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QPixmap

# =========================================================
#  설정
# =========================================================
IS_TEST_MODE = True  

try:
    if IS_TEST_MODE:
        from test.cry_api_test import CryApiThread
    else:
        from api.cry_api import CryApiThread
except ImportError:
    # 더미 클래스 (파일이 없을 경우 대비)
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

# [저장 경로 설정]
SAVE_ROOT_DIR = r"D:/data"
DELAY_COUNT = 4 

# [카메라 설정]
RTSP_DUMMY = r"D:/GitHub/program/output.avi" # 테스트용 더미 파일 경로 확인 필요
RTSP_URLS = {
    "car":      RTSP_DUMMY,
    "wheel_ws": RTSP_DUMMY,
    "wheel_ds": RTSP_DUMMY,
    "waek_ws1": RTSP_DUMMY,
    "waek_ds1": RTSP_DUMMY,
    "waek_ws2": RTSP_DUMMY,
    "waek_ds2": RTSP_DUMMY,
}

# [소음 센서 설정]
CRY_CONFIGS = {
    "waek_ws1": {"ip": "192.168.1.211", "port": 90, "user": "admin", "pw": "crysound"},
    "waek_ds1": {"ip": "192.168.1.213", "port": 90, "user": "admin", "pw": "crysound"},
    "waek_ws2": {"ip": "192.168.1.212", "port": 90, "user": "admin", "pw": "crysound"},
    "waek_ds2": {"ip": "192.168.1.214", "port": 90, "user": "admin", "pw": "crysound"},
}


# =========================================================
#  스레드 클래스 정의
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
            
            # 테이블 구조 생성 (이미지 경로, 소음 데이터, 휠 상태 등)
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
        except Exception as e:
            print(f"DB Init Error: {e}")
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
            w = d.get('wheel_status', {}) # 텍스트 변환된 상태값 (회전/정상 등)
            raw = d.get('wheel_raw', {})  # 원본 숫자값 (필요시 사용, 여기서는 status 사용)
            i = d.get('images', {})

            # 휠 상태값이 텍스트가 아닌 경우를 대비해 기본 처리 (DB에는 raw값 대신 status 텍스트 저장 가정)
            # 만약 DB에 숫자를 넣고 싶으면 w 대신 raw 사용
            
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
            print(f"DB Save Error: {e}")
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
        sock.connect("tcp://192.168.0.103:5577")
        #sock.connect("tcp://127.0.0.1:5888")
        while self.running:
            try:
                if sock.poll(100):
                    self.msg_received.emit(json.loads(sock.recv_string()))
            except: pass

    def stop(self):
        self.running = False
        self.wait()

# =========================================================
#  🖥️ 메인 윈도우
# =========================================================
class MainWindow(QMainWindow):
    CONFIG_FILE = "config.json" # 설정 파일 이름

    def __init__(self):
        super().__init__()
        # UI 파일 로드
        ui_path = os.path.join(os.path.dirname(__file__), "window_hmi.ui")
        loadUi(ui_path, self)

        # 1. 자료구조 초기화
        self.car_queue = deque()        
        self.history_queue = deque(maxlen=172) 
        self.init_table_widget()

        # 2. 설정 불러오기 및 UI 초기화
        self.load_config() 
        self.pushButton_2.clicked.connect(self.save_config)

        # [NEW] 히스토리 버튼(N_1 ~ N_172) 이벤트 연결
        self.connect_history_buttons()

        # 3. 스레드 시작
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

    # =========================================================
    #  [기능] 설정(Config) 관리
    # =========================================================
    def load_config(self):
        """JSON 파일에서 설정을 읽어오고 UI에 반영"""
        default_config = {"red": 70.0, "yellow": 60.0, "blue": 50.0}
        
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    self.config_data = json.load(f)
            except Exception as e:
                print(f"설정 파일 로드 오류: {e}")
                self.config_data = default_config
        else:
            self.config_data = default_config
        
        self.lineEdit_2.setText(str(self.config_data.get("red", 70)))
        self.lineEdit_3.setText(str(self.config_data.get("yellow", 60)))
        self.lineEdit_4.setText(str(self.config_data.get("blue", 50)))

    def save_config(self):
        """UI 입력값을 JSON으로 저장하고 버튼 색상 갱신"""
        try:
            red_val = float(self.lineEdit_2.text())
            yel_val = float(self.lineEdit_3.text())
            blu_val = float(self.lineEdit_4.text())
            
            self.config_data = {
                "red": red_val, "yellow": yel_val, "blue": blu_val
            }

            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=4)
            
            print("설정이 저장되었습니다.")
            self.update_buttons() # 변경된 설정으로 버튼 색상 즉시 적용
            
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "숫자만 입력해주세요.")
        except Exception as e:
            QMessageBox.critical(self, "저장 오류", f"설정 저장 중 오류 발생: {e}")

    # =========================================================
    #  [기능] 히스토리 버튼 및 뷰어 실행
    # =========================================================
    def connect_history_buttons(self):
        """N_1 ~ N_172 버튼에 클릭 이벤트 연결"""
        for i in range(1, 173):
            btn_name = f"N_{i}"
            if hasattr(self, btn_name):
                btn = getattr(self, btn_name)
                # lambda에 idx=i를 바인딩하여 각 버튼이 올바른 인덱스를 가지도록 함
                btn.clicked.connect(lambda _, idx=i: self.on_history_btn_clicked(idx))

    def on_history_btn_clicked(self, btn_idx):
        """버튼 클릭 시 해당 인덱스의 데이터로 뷰어 실행"""
        # history_queue는 0부터 시작, 버튼은 1부터 시작 (N_1 -> index 0)
        q_idx = btn_idx - 1
        
        # 큐 범위 내에 데이터가 있는지 확인
        if q_idx < len(self.history_queue):
            data = self.history_queue[q_idx]
            car_no = data.get("car_no")
            
            if car_no:
                self.open_viewer(str(car_no))
            else:
                QMessageBox.information(self, "알림", "해당 칸에 대차 번호 정보가 없습니다.")
        else:
             # 데이터가 아직 없는 빈 버튼 클릭 시
             pass

    def open_viewer(self, car_no):
        """viewer.py를 서브프로세스로 실행"""
        try:
            # main.py와 동일한 위치에 viewer.py가 있다고 가정
            viewer_path = os.path.join(os.path.dirname(__file__), "viewer.py")
            
            if not os.path.exists(viewer_path):
                QMessageBox.warning(self, "오류", f"뷰어 파일(viewer.py)을 찾을 수 없습니다.\n경로: {viewer_path}")
                return

            # python viewer.py [car_no] 실행
            subprocess.Popen([sys.executable, viewer_path, car_no])
            print(f"🚀 뷰어 실행 요청: Car No {car_no}")
            
        except Exception as e:
            QMessageBox.critical(self, "실행 오류", f"뷰어 실행 중 오류 발생:\n{e}")

    # =========================================================
    #  [기능] UI 및 데이터 처리
    # =========================================================
    def init_table_widget(self):
        cols = ["대차번호", "WS1", "DS1", "WS2", "DS2", "휠 WS", "휠 DS"]
        self.tableWidget.setColumnCount(len(cols))
        self.tableWidget.setHorizontalHeaderLabels(cols)
        self.tableWidget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def get_rotation_text(self, val):
        if val == 1: return "회전"
        elif val == 2: return "무회전"
        return "감지X"

    def get_position_text(self, val):
        if val == 1: return "정상"
        elif val == 2: return "비정상"
        return "감지X"

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

    # def process_zmq(self, data):
    #     msg_type = data.get("type")
    #     event_id = data.get("event_id")
    #     print(f"📥 [ZMQ 수신]: {data}")

    #     if msg_type == "car_event" and data.get("event") == "START":
    #         ts_str = datetime.now().strftime("%H%M%S_%f")[:-3]
    #         new_car = {
    #             "event_id": event_id,
    #             "car_no": None,
    #             "sensor_data": {},
    #             "wheel_status": {}, 
    #             "wheel_raw": {},    
    #             "images": {},
    #         }
    #         for cam in ["car", "wheel_ws", "wheel_ds", "waek_ws1", "waek_ds1"]:
    #             new_car["images"][cam] = self.trigger_save_and_get_path(cam, ts_str)
            
    #         self.car_queue.append(new_car)
    #         print(f"📊 [큐 상태] 현재개수: {len(self.car_queue)} / 설정값: {DELAY_COUNT}")
    #         if len(self.car_queue) > DELAY_COUNT:
    #             print(f"👋 [POP 발생] 큐가 꽉 차서 맨 앞 차량 삭제됨!")
    #         self.check_queue_pop()

    #     elif msg_type in ["car_no", "wheel_status"]:
    #         target_car = None
    #         for car in reversed(self.car_queue):
    #             if car.get("event_id") == event_id:
    #                 target_car = car
    #                 break
            
    #         if target_car:
    #             if msg_type == "car_no":
    #                 target_car["car_no"] = data.get("car_no")
    #                 print(f"✅ 매칭 성공! ID: {event_id}")
    #             elif msg_type == "wheel_status":
    #                 pos, src = data.get("pos", "").lower(), data.get("src", "").lower()
    #                 r, p = data.get("wheel1_rotation", 0), data.get("wheel1_position", 0)
                    
    #                 target_car["wheel_status"][f"{pos}_{src}_r"] = self.get_rotation_text(r)
    #                 target_car["wheel_status"][f"{pos}_{src}_p"] = self.get_position_text(p)
    #                 target_car["wheel_raw"][f"{pos}_{src}_r"] = r
    #                 target_car["wheel_raw"][f"{pos}_{src}_p"] = p
    #                 print(f"❌ 매칭 실패 (이미 삭제됨): {event_id} / Type: {msg_type}")

    def process_zmq(self, data):
        msg_type = data.get("type")
        event_id = data.get("event_id")
        
        print(f"📥 [ZMQ 수신]: {data}") # 디버깅용

        if msg_type == "car_event" and data.get("event") == "START":
            ts_str = datetime.now().strftime("%H%M%S_%f")[:-3]
            new_car = {
                "event_id": event_id,
                "car_no": None,
                "sensor_data": {},
                "wheel_status": {}, # 텍스트용 ("정상", "회전" 등)
                "wheel_raw": {},    # 숫자용 (1, 0, 2) [이게 있어야 HMI 색상이 나옴]
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
                    print(f"✅ [CarNo] 매칭 성공: {data.get('car_no')}")
                elif msg_type == "wheel_status":
                    pos, src = data.get("pos", "").lower(), data.get("src", "").lower()
                    r, p = data.get("wheel1_rotation", 0), data.get("wheel1_position", 0)
                    
                    # 1. 텍스트 저장 (표시용)
                    target_car["wheel_status"][f"{pos}_{src}_r"] = self.get_rotation_text(r)
                    target_car["wheel_status"][f"{pos}_{src}_p"] = self.get_position_text(p)
                    
                    # 2. [중요] 숫자 원본 저장 (버튼 색상 결정용)
                    target_car["wheel_raw"][f"{pos}_{src}_r"] = r
                    target_car["wheel_raw"][f"{pos}_{src}_p"] = p
                    
                    print(f"✅ [Wheel] 매칭 및 저장 완료: {pos}_{src}")
            else:
                pass
                print(f"❌ 매칭 실패: {event_id} (큐에서 이미 삭제됨)")

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
        self.update_labels_and_images(data)
        self.add_row_to_table(data)
        self.history_queue.appendleft(data)
        self.update_buttons()

    def update_labels_and_images(self, data):
        imgs = data.get('images', {})
        self.show_img("image_1", imgs.get("car"))
        self.show_img("image_2", imgs.get("waek_ws1"))
        self.show_img("image_3", imgs.get("waek_ds1"))
        self.show_img("image_4", imgs.get("waek_ws2"))
        self.show_img("image_5", imgs.get("waek_ds2"))
        self.show_img("image_6", imgs.get("wheel_ws"))
        self.show_img("image_7", imgs.get("wheel_ds"))
        
        sens = data.get('sensor_data', {})
        wheels = data.get('wheel_status', {})

        def set_txt(label_name, txt):
            if hasattr(self, label_name):
                getattr(self, label_name).setText(str(txt))

        c_no = data.get("car_no")
        set_txt("msg_1", c_no if c_no else "-")
        set_txt("msg_2", f"{sens.get('waek_ws1', 0):.2f}")
        set_txt("msg_3", f"{sens.get('waek_ds1', 0):.2f}")
        set_txt("msg_4", f"{sens.get('waek_ws2', 0):.2f}")
        set_txt("msg_5", f"{sens.get('waek_ds2', 0):.2f}")

        def fmt_wheel(pos, src):
            r = wheels.get(f"{pos}_{src}_r")
            p = wheels.get(f"{pos}_{src}_p")
            r_txt = r if r else "-"
            p_txt = p if p else "-"
            return f"{r_txt}/{p_txt}"

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
        # [중요] HMI에 표시할 때 'wheel_raw' 값을 기반으로 판단
        raw = data.get("wheel_raw", {})
        vals = []

        for src in ["1st", "2nd"]:
            # 회전(r)과 위치(p) 둘 중 하나라도 들어왔는지 확인
            r_val = raw.get(f"{pos}_{src}_r")
            p_val = raw.get(f"{pos}_{src}_p")
            
            if r_val is not None: vals.append(r_val)
            if p_val is not None: vals.append(p_val)

        if not vals:
            return "감지X"  # 데이터가 하나도 안 들어옴
        if 2 in vals:
            return "비정상" # 하나라도 비정상이면
        if 0 in vals:
            return "감지X" # (0: 인식실패)가 섞여있으면
        return "정상" # 나머지는 정상(1)

    def update_buttons(self):
        # 설정값 가져오기
        red_th = self.config_data.get("red", 70)
        yel_th = self.config_data.get("yellow", 60)
        blu_th = self.config_data.get("blue", 50)

        for i, car_data in enumerate(self.history_queue):
            btn_num = i + 1
            if btn_num > 172: break
            
            btn_name = f"N_{btn_num}"
            if not hasattr(self, btn_name): continue
            
            btn = getattr(self, btn_name)
            
            # 1. 위쪽 색상 (소음 기준)
            sens = car_data.get("sensor_data", {})
            max_db = max(
                sens.get('waek_ws1', 0), sens.get('waek_ds1', 0),
                sens.get('waek_ws2', 0), sens.get('waek_ds2', 0)
            )
            
            top_color = "white"
            if max_db > red_th: top_color = "red"
            elif max_db > yel_th: top_color = "yellow"
            elif max_db > blu_th: top_color = "#00BFFF" 
            
            # 2. 아래쪽 색상 (휠 상태)
            raw = car_data.get("wheel_raw", {})
            all_vals = list(raw.values())
            
            if not all_vals: 
                bottom_status = "NG"
                bottom_color = "yellow"
            else:
                if 2 in all_vals:
                    bottom_status = "NO"
                    bottom_color = "red"
                elif 0 in all_vals:
                    bottom_status = "NG"
                    bottom_color = "yellow"
                else:
                    bottom_status = "OK"
                    bottom_color = "white"

            style = f"""
                QPushButton {{
                    background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {top_color}, stop:0.5 {top_color}, 
                        stop:0.501 {bottom_color}, stop:1 {bottom_color});
                    border: 1px solid gray;
                    color: black; 
                    font-weight: bold;
                    font-size: 8pt;
                    padding: 0px;
                    margin: 0px;
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