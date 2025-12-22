#workers/threads_zmq_rtsp.py
import time
import zmq
import cv2

from PyQt5.QtCore import QThread, pyqtSignal

from utils.image_utils import decode_jpeg_to_bgr, qimage_from_bgr, cvimg_to_qimage


class ZmqRecvThread(QThread):
    """
    ZeroMQ PULL 소켓으로 문자열(JSON 포함)만 수신하는 스레드
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
            try:
                msg = self.sock.recv_string()
            except zmq.error.Again:
                continue
            except Exception as e:
                print(f"[WARN] ZMQ recv error → reconnect: {e}")
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

        print("[INFO] ZmqRecvThread 종료")


class RtspThread(QThread):
    """
    RTSP 스트림을 읽어 QImage/BGR 프레임을 시그널로 내보내는 스레드.
    연결 실패 또는 프레임 읽기 실패가 일정 횟수 이상 발생하면
    RTSP에 재연결을 시도한다.
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

        self.reconnect_delay = reconnect_delay
        self.max_read_fail = max_read_fail
        self.frame_interval = frame_interval

    def stop(self):
        self._running = False

    def _open_capture(self):
        """RTSP 캡처를 연다."""
        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap.release()
            return None
        return cap

    def run(self):
        cap = None
        read_fail_count = 0

        while self._running:
            # 캡처 객체가 없거나 닫혀 있으면 재연결 시도
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
                # 잠시 대기 후 다시 시도
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

            # 프레임 정상 읽힘
            read_fail_count = 0
            qimg = cvimg_to_qimage(frame)
            if qimg is None:
                continue

            self.frame_ready.emit(qimg, frame)

            # FPS 너무 높지 않게 약간의 sleep (필요시 조절)
            if self.frame_interval > 0:
                time.sleep(self.frame_interval)

        # 루프 종료 시 자원 정리
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        print(f"[INFO] {self.name} 스레드 종료")
