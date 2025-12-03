import time
import zmq
import cv2

from PyQt5.QtCore import QThread, pyqtSignal

from image_utils import decode_jpeg_to_bgr, qimage_from_bgr, cvimg_to_qimage

class ZmqRecvThread(QThread):
    frame_ready = pyqtSignal(object, object, str)  # QImage, BGR, code

    def __init__(self, pull_connect, parent=None):
        super().__init__(parent)
        self.pull_connect = pull_connect
        self._running = True
        self.ctx = None
        self.sock = None

    def stop(self):
        self._running = False

    def run(self):
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.PULL)
        self.sock.setsockopt(zmq.RCVHWM, 1)
        self.sock.setsockopt(zmq.RCVTIMEO, 1000)
        #self.sock.setsockopt(zmq.CONFLATE, 1)
        self.sock.connect(self.pull_connect)

        while self._running:
            try:
                parts = self.sock.recv_multipart()
            except zmq.error.Again:
                continue
            except Exception:
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

        try:
            if self.sock is not None:
                self.sock.close(0)
        except Exception:
            pass

class RtspThread(QThread):
    frame_ready = pyqtSignal(object, object)  # QImage, BGR

    def __init__(self, rtsp_url, name="RTSP", parent=None):
        super().__init__(parent)
        self.rtsp_url = rtsp_url
        self.name = name
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            print("[ERR] {} RTSP 연결 실패: {}".format(self.name, self.rtsp_url))
            return

        while self._running:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.02)
                continue

            qimg = cvimg_to_qimage(frame)
            self.frame_ready.emit(qimg, frame)

        cap.release()
        print("[INFO] {} 스레드 종료".format(self.name))
