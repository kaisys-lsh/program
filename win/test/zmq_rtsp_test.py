#test/threads_zmq_rtsp.py#
import time
import zmq
import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from utils.image_utils import cvimg_to_qimage


class ZmqRecvThread(QThread):
    """
    ZeroMQ PULL 소켓으로 문자열(번호/JSON)만 수신하는 스레드 (TEST용)
    """
    text_ready = pyqtSignal(str)

    def __init__(
        self,
        pull_connect,
        parent=None,
        rcv_timeout_ms: int = 1000,
        reconnect_delay: float = 1.0,
    ):
        super().__init__(parent)
        self.pull_connect = pull_connect
        self._running = True
        self.ctx = None
        self.sock = None

        self.rcv_timeout_ms = rcv_timeout_ms
        self.reconnect_delay = reconnect_delay

    def stop(self):
        self._running = False

    def _create_and_connect_socket(self):
        """소켓을 새로 만들고 서버에 연결한다."""
        if self.sock is not None:
            try:
                self.sock.close(0)
            except Exception:
                pass

        if self.ctx is None:
            self.ctx = zmq.Context.instance()

        sock = self.ctx.socket(zmq.PULL)
        sock.setsockopt(zmq.RCVHWM, 1)
        sock.setsockopt(zmq.RCVTIMEO, self.rcv_timeout_ms)
        sock.connect(self.pull_connect)
        self.sock = sock

    def run(self):
        self._create_and_connect_socket()

        while self._running:
            if self.sock is None:
                try:
                    self._create_and_connect_socket()
                except Exception as e:
                    print(f"[ERR] ZMQ 소켓 재생성 실패: {e}")
                    time.sleep(self.reconnect_delay)
                    continue

            try:
                msg = self.sock.recv_string()
            except zmq.error.Again:
                continue
            except Exception as e:
                print(f"[WARN] ZMQ recv 예외 발생, 재연결 시도: {e}")
                try:
                    self.sock.close(0)
                except Exception:
                    pass
                self.sock = None
                time.sleep(self.reconnect_delay)
                continue

            if not self._running:
                break

            self.text_ready.emit(msg)

        try:
            if self.sock is not None:
                self.sock.close(0)
        except Exception:
            pass
        self.sock = None
        print("[INFO] ZmqRecvThread 종료")


class RtspThread(QThread):
    frame_ready = pyqtSignal(object, object)  # QImage, BGR

    def __init__(self, rtsp_url, name="RTSP_DUMMY", parent=None, **kwargs):
        super().__init__(parent)
        self._running = True
        self.name = name

    def stop(self):
        self._running = False

    def run(self):
        import datetime

        while self._running:
            img = np.zeros((480, 640, 3), dtype=np.uint8)
            img[:] = (0, 0, 0)

            now_str = datetime.datetime.now().strftime("%H:%M:%S")

            cv2.putText(img, self.name, (50, 200),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                        (255, 255, 255), 2)

            cv2.putText(img, now_str, (50, 260),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                        (255, 255, 255), 2)

            qimg = cvimg_to_qimage(img)
            self.frame_ready.emit(qimg, img.copy())

            time.sleep(0.1)
