#threads_zmq_rtsp.py
import time
import zmq
import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from utils.image_utils import decode_jpeg_to_bgr, qimage_from_bgr, cvimg_to_qimage


class ZmqRecvThread(QThread):
    """
    ZeroMQ PULL 소켓을 통해 JPEG 이미지를 수신하고,
    QImage/BGR 프레임과 함께 코드 문자열을 시그널로 내보내는 스레드.
    연결 에러 발생 시 자동 재연결을 시도한다.
    """
    frame_ready = pyqtSignal(object, object, str)  # QImage, BGR, code

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
        # sock.setsockopt(zmq.CONFLATE, 1)
        sock.connect(self.pull_connect)
        self.sock = sock

    def run(self):
        self._create_and_connect_socket()

        while self._running:
            if self.sock is None:
                # 소켓이 없으면 재생성 후 재연결
                try:
                    self._create_and_connect_socket()
                except Exception as e:
                    print(f"[ERR] ZMQ 소켓 재생성 실패: {e}")
                    time.sleep(self.reconnect_delay)
                    continue

            try:
                parts = self.sock.recv_multipart()
            except zmq.error.Again:
                # 타임아웃: 그냥 다음 루프로
                continue
            except Exception as e:
                # 소켓 관련 예외 → 재연결 시도
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
            if len(parts) != 2:
                continue

            code_bytes, jpg_bytes = parts
            code = code_bytes.decode("utf-8") if code_bytes else ""
            bgr = decode_jpeg_to_bgr(jpg_bytes)
            if bgr is None:
                continue
            qimg = qimage_from_bgr(bgr)
            if qimg is None:
                continue

            self.frame_ready.emit(qimg, bgr, code)

        # 종료 시 소켓 정리
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
            # 기본 파란 바탕
            img = np.zeros((480, 640, 3), dtype=np.uint8)
            img[:] = (255, 0, 0)

            # 현재 시간 문자열 (예: 2025-01-02 12:34:56)
            now_str = datetime.datetime.now().strftime("%H:%M:%S")

            # 이름 표시
            cv2.putText(img, self.name, (50, 200),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                        (255, 255, 255), 2)

            # 현재 시간 표시
            cv2.putText(img, now_str, (50, 260),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                        (255, 255, 255), 2)

            # PyQt에 전달
            qimg = cvimg_to_qimage(img)
            self.frame_ready.emit(qimg, img.copy())

            time.sleep(0.1)

