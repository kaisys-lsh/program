# workers/threads_zmq_rtsp.py
import time
import zmq
import cv2

from PyQt5.QtCore import QThread, pyqtSignal

from utils.image_utils import cvimg_to_qimage


class ZmqRecvThread(QThread):
    """
    ZeroMQ PULL 소켓으로 문자열(JSON 포함)만 수신하는 스레드
    - 서버에서 여러 JSON이 '\n'으로 붙어서 올 수 있으니
      여기서 라인 단위로 쪼개 emit 한다.
    """
    text_ready = pyqtSignal(str)

    def __init__(
        self,
        pull_connect,
        parent=None,
        rcv_timeout_ms: int = 1000,
        reconnect_delay: float = 1.0,
        rcv_hwm: int = 100,   # 1포트로 여러 이벤트가 오므로 HWM 여유 있게
    ):
        super().__init__(parent)
        self.pull_connect = pull_connect
        self._running = True
        self.ctx = None
        self.sock = None

        self.rcv_timeout_ms = int(rcv_timeout_ms)
        self.reconnect_delay = float(reconnect_delay)
        self.rcv_hwm = int(rcv_hwm)

    def stop(self):
        self._running = False

    def _create_and_connect_socket(self):
        if self.sock is not None:
            try:
                self.sock.close(0)
            except Exception:
                pass
            self.sock = None

        if self.ctx is None:
            self.ctx = zmq.Context.instance()

        sock = self.ctx.socket(zmq.PULL)

        # 끊을 때 바로 종료되게
        try:
            sock.setsockopt(zmq.LINGER, 0)
        except Exception:
            pass

        # 수신 버퍼 여유
        try:
            sock.setsockopt(zmq.RCVHWM, self.rcv_hwm)
        except Exception:
            pass

        # recv timeout
        try:
            sock.setsockopt(zmq.RCVTIMEO, self.rcv_timeout_ms)
        except Exception:
            pass

        sock.connect(self.pull_connect)
        self.sock = sock

    def run(self):
        self._create_and_connect_socket()

        while self._running:
            try:
                msg_bytes = self.sock.recv()
            except zmq.error.Again:
                continue
            except Exception as e:
                print(f"[WARN] ZMQ recv error → reconnect: {e}")
                try:
                    if self.sock is not None:
                        self.sock.close(0)
                except Exception:
                    pass
                self.sock = None
                time.sleep(self.reconnect_delay)
                self._create_and_connect_socket()
                continue

            if not self._running:
                break

            try:
                msg = msg_bytes.decode("utf-8", errors="ignore")
            except Exception:
                continue

            if not msg:
                continue

            # \x00 같은 찌꺼기 제거 + 공백 정리
            msg = msg.replace("\x00", "").strip()
            if not msg:
                continue

            # 여러 줄로 붙어올 수 있으니 여기서 분리해서 emit
            if "\n" in msg:
                for ln in msg.splitlines():
                    ln = ln.strip()
                    if ln:
                        self.text_ready.emit(ln)
            else:
                self.text_ready.emit(msg)

        try:
            if self.sock is not None:
                self.sock.close(0)
        except Exception:
            pass

        print("[INFO] ZmqRecvThread 종료")


class RtspThread(QThread):
    """
    RTSP 스트림을 읽어 QImage/BGR 프레임을 시그널로 내보내는 스레드.
    연결 실패 또는 프레임 읽기 실패가 일정 횟수 이상 발생하면 재연결 시도.
    """
    frame_ready = pyqtSignal(object, object)  # QImage, BGR

    def __init__(
        self,
        rtsp_url,
        name="RTSP",
        parent=None,
        reconnect_delay: float = 2.0,
        max_read_fail: int = 50,
        frame_interval: float = 0.02,
    ):
        super().__init__(parent)
        self.rtsp_url = rtsp_url
        self.name = name
        self._running = True

        self.reconnect_delay = float(reconnect_delay)
        self.max_read_fail = int(max_read_fail)
        self.frame_interval = float(frame_interval)

    def stop(self):
        self._running = False

    def _open_capture(self):
        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            try:
                cap.release()
            except Exception:
                pass
            return None
        return cap

    def run(self):
        cap = None
        read_fail_count = 0

        while self._running:
            if cap is None or not cap.isOpened():
                print(f"[INFO] {self.name} RTSP 연결 시도: {self.rtsp_url}")
                cap = self._open_capture()
                if cap is None:
                    print(f"[ERR] {self.name} RTSP 연결 실패, {self.reconnect_delay}초 후 재시도")
                    time.sleep(self.reconnect_delay)
                    continue
                print(f"[INFO] {self.name} RTSP 연결 성공")

            ok, frame = cap.read()

            if not ok or frame is None:
                read_fail_count += 1
                time.sleep(self.frame_interval)

                if read_fail_count >= self.max_read_fail:
                    print(f"[WARN] {self.name} 프레임 읽기 {read_fail_count}회 연속 실패, 재연결 시도")
                    try:
                        cap.release()
                    except Exception:
                        pass
                    cap = None
                    read_fail_count = 0
                    time.sleep(self.reconnect_delay)
                continue

            read_fail_count = 0

            qimg = cvimg_to_qimage(frame)
            if qimg is None:
                continue

            self.frame_ready.emit(qimg, frame)

            if self.frame_interval > 0:
                time.sleep(self.frame_interval)

        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        print(f"[INFO] {self.name} 스레드 종료")
