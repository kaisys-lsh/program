# win/workers/threads_rtsp.py
import cv2
import time
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage
from utils.image_utils import cvimg_to_qimage

class RtspThread(QThread):
    frame_ready = pyqtSignal(object, object)  # QImage, BGR

    def __init__(self, rtsp_url, name="RTSP", parent=None):
        super().__init__(parent)
        self.url = rtsp_url
        self.name = name
        self._running = True

    def stop(self):
        self._running = False
        self.quit()
        self.wait()

    def run(self):
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        
        while self._running:
            if not cap.isOpened():
                time.sleep(2.0)
                cap.open(self.url, cv2.CAP_FFMPEG)
                continue

            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            qimg = cvimg_to_qimage(frame)
            if qimg:
                self.frame_ready.emit(qimg, frame)
            
            time.sleep(0.01)

        cap.release()