import os
from datetime import datetime

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QImage, QPixmap

from config import DATA_ROOT

# ─────────────────────────────────────────
# QImage / OpenCV 변환
# ─────────────────────────────────────────
def cvimg_to_qimage(img_bgr):
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    h, w, ch = img_rgb.shape
    return QImage(img_rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()

def decode_jpeg_to_bgr(jpg_bytes: bytes):
    arr = np.frombuffer(jpg_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # BGR
    return img

def qimage_from_bgr(img_bgr):
    if img_bgr is None:
        return None
    return cvimg_to_qimage(img_bgr)

def set_label_pixmap_fill(label, pixmap):
    if label is None or pixmap is None or pixmap.isNull():
        return

    target_size = label.size()
    if target_size.width() <= 0 or target_size.height() <= 0:
        label.setPixmap(pixmap.scaled(500, 480, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        label.setAlignment(Qt.AlignCenter)
        return

    scaled = pixmap.scaled(target_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)

    if scaled.width() > target_size.width() or scaled.height() > target_size.height():
        x = max(0, (scaled.width() - target_size.width()) // 2)
        y = max(0, (scaled.height() - target_size.height()) // 2)
        rect = QRect(x, y, target_size.width(), target_size.height())
        scaled = scaled.copy(rect)

    label.setPixmap(scaled)
    label.setAlignment(Qt.AlignCenter)

# ─────────────────────────────────────────
# 경로 / 저장 유틸
# ─────────────────────────────────────────
def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)
    return path

def ws_car1_path(dt: datetime, car_no: str):
    date_str = dt.strftime("%Y%m%d")
    time_str = dt.strftime("%H%M%S")
    folder = os.path.join(DATA_ROOT, "car1", date_str)
    ensure_dir(folder)
    return os.path.join(folder, f"{car_no}_{time_str}.jpg")

def ws_leak1_path(dt: datetime, car_no: str):
    date_str = dt.strftime("%Y%m%d")
    time_str = dt.strftime("%H%M%S")
    folder = os.path.join(DATA_ROOT, "WS_leak1", date_str)
    ensure_dir(folder)
    return os.path.join(folder, f"{car_no}_{time_str}.jpg")

def ds_leak1_path(dt: datetime, car_no: str):
    date_str = dt.strftime("%Y%m%d")
    time_str = dt.strftime("%H%M%S")
    folder = os.path.join(DATA_ROOT, "DS_leak1", date_str)
    ensure_dir(folder)
    return os.path.join(folder, f"{car_no}_{time_str}.jpg")

def ws_leak2_path(dt: datetime, car_no: str):
    date_str = dt.strftime("%Y%m%d")
    time_str = dt.strftime("%H%M%S")
    folder = os.path.join(DATA_ROOT, "WS_leak2", date_str)
    ensure_dir(folder)
    return os.path.join(folder, f"{car_no}_{time_str}.jpg")

def ds_leak2_path(dt: datetime, car_no: str):
    date_str = dt.strftime("%Y%m%d")
    time_str = dt.strftime("%H%M%S")
    folder = os.path.join(DATA_ROOT, "DS_leak2", date_str)
    ensure_dir(folder)
    return os.path.join(folder, f"{car_no}_{time_str}.jpg")



def ws_wheel1_path(dt: datetime, car_no: str):
    date_str = dt.strftime("%Y%m%d")
    time_str = dt.strftime("%H%M%S")
    folder = os.path.join(DATA_ROOT, "WS_wheel1", date_str)
    ensure_dir(folder)
    return os.path.join(folder, f"{car_no}_{time_str}.jpg")

def ds_wheel1_path(dt: datetime, car_no: str):
    date_str = dt.strftime("%Y%m%d")
    time_str = dt.strftime("%H%M%S")
    folder = os.path.join(DATA_ROOT, "DS_wheel1", date_str)
    ensure_dir(folder)
    return os.path.join(folder, f"{car_no}_{time_str}.jpg")



def save_bgr_image_to_file(bgr, out_path: str) -> bool:
    if bgr is None:
        return False
    ensure_dir(os.path.dirname(out_path))
    try:
        ok = cv2.imwrite(out_path, bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return bool(ok)
    except Exception:
        return False
