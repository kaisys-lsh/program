# utils/image_utils.py
# --------------------------------------------------
# 이미지 저장 + OpenCV->QImage 변환 + QLabel 표시 유틸 (통합본)
# --------------------------------------------------

import os
import cv2
from datetime import datetime

from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtCore import Qt

from config.config import DATA_ROOT


def _ensure_dir(path: str):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


# ==================================================
# 1) 파일 저장
# ==================================================
def event_dir(event_id: str) -> str:
    # ✅ event_id None/빈값 방어
    if not event_id:
        event_id = "UNKNOWN"
    event_id = str(event_id).strip()
    if not event_id:
        event_id = "UNKNOWN"

    base = os.path.join(DATA_ROOT, event_id)
    _ensure_dir(base)
    return base


def save_bgr_image(event_id: str, bgr, name: str) -> str:
    """
    BGR 이미지 저장
    - name 예: img_cam1 / img_ws1 / img_ds1 / img_ws2 / img_ds2 / img_wheel_ws / ...
    """
    if bgr is None:
        return ""

    base = event_dir(event_id)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = "{0}_{1}.jpg".format(name, ts)

    path = os.path.join(base, filename)
    try:
        cv2.imwrite(path, bgr)
        return path
    except Exception as e:
        print("[IMG-SAVE-ERR]", e)
        return ""


# ==================================================
# 2) OpenCV(BGR) -> QImage 변환 (기존 테스트 코드 호환)
# ==================================================
def cvimg_to_qimage(bgr):
    """
    OpenCV BGR ndarray -> QImage
    test/zmq_rtsp_test.py 등에서 사용
    """
    if bgr is None:
        return QImage()

    try:
        # ✅ 연속 메모리 보장 (ROI/슬라이스에서 깨짐 방지)
        try:
            import numpy as np
            bgr = np.ascontiguousarray(bgr)
        except Exception:
            pass

        if len(bgr.shape) == 2:
            # Grayscale
            h, w = bgr.shape
            bytes_per_line = w
            return QImage(bgr.data, w, h, bytes_per_line, QImage.Format_Grayscale8).copy()

        if len(bgr.shape) == 3:
            h, w, ch = bgr.shape
            if ch == 3:
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                bytes_per_line = ch * w
                return QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()

            if ch == 4:
                rgba = cv2.cvtColor(bgr, cv2.COLOR_BGRA2RGBA)
                bytes_per_line = ch * w
                return QImage(rgba.data, w, h, bytes_per_line, QImage.Format_RGBA8888).copy()

    except Exception:
        pass

    return QImage()


# ==================================================
# 3) QLabel 표시 (기존 main/table/button 호환)
# ==================================================
def set_label_pixmap_fill(label, pixmap: QPixmap):
    """
    QLabel에 pixmap을 비율 유지한 채 표시
    """
    if label is None or pixmap is None or pixmap.isNull():
        return

    try:
        w = label.width()
        h = label.height()
        if w <= 0 or h <= 0:
            return

        pm = pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        label.setPixmap(pm)
        label.setAlignment(Qt.AlignCenter)
    except Exception:
        pass
