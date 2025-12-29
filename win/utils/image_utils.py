# utils/image_utils.py
import os
import re
from datetime import datetime

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QImage, QPixmap

from config.config import DATA_ROOT


# ─────────────────────────────────────────
# 내부 유틸
# ─────────────────────────────────────────
def _safe_name(s: str) -> str:
    """
    파일명에 쓰기 안전하게 최소한만 치환.
    """
    if s is None:
        return "none"
    s = str(s).strip()
    if not s:
        return "none"
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", s)
    return s


def _event_id_to_datetime(event_id: str):
    """
    event_id 안의 epoch ms(예: car-1766983491957-xxxx)를 뽑아 datetime으로 변환.
    실패하면 None.
    """
    if not event_id:
        return None

    s = str(event_id).strip()
    if not s:
        return None

    # 가장 긴 숫자 덩어리를 epoch(ms)로 가정
    m = re.search(r"(\d{10,})", s)
    if not m:
        return None

    try:
        ms = int(m.group(1))
        # ms가 초 단위로 들어올 가능성 방어
        if ms < 10_000_000_000:  # 10자리면 초 가능성
            return datetime.fromtimestamp(ms)
        return datetime.fromtimestamp(ms / 1000.0)
    except Exception:
        return None


# ─────────────────────────────────────────
# QImage / OpenCV 변환
# ─────────────────────────────────────────
def cvimg_to_qimage(img_bgr):
    if img_bgr is None:
        return None

    try:
        if len(img_bgr.shape) == 2:
            h, w = img_bgr.shape
            q = QImage(img_bgr.data, w, h, w, QImage.Format_Grayscale8).copy()
            return q

        if img_bgr.shape[2] == 4:
            img_rgba = cv2.cvtColor(img_bgr, cv2.COLOR_BGRA2RGBA)
            h, w, ch = img_rgba.shape
            return QImage(img_rgba.data, w, h, ch * w, QImage.Format_RGBA8888).copy()

        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = img_rgb.shape
        return QImage(img_rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()

    except Exception:
        return None


def decode_jpeg_to_bgr(jpg_bytes: bytes):
    if not jpg_bytes:
        return None
    try:
        arr = np.frombuffer(jpg_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # BGR
        return img
    except Exception:
        return None


def qimage_from_bgr(img_bgr):
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


# ---- (기존 방식) car_no + time 파일명 (레거시, 호환용) ----
def _make_path_legacy(subdir: str, dt: datetime, car_no: str):
    date_str = dt.strftime("%Y%m%d")
    time_str = dt.strftime("%H%M%S")
    car_no = _safe_name(car_no)
    folder = os.path.join(DATA_ROOT, subdir, date_str)
    ensure_dir(folder)
    return os.path.join(folder, f"{car_no}_{time_str}.jpg")


# ---- (신규 방식) event_id 고정 파일명 (덮어쓰기용) ----
def _make_path_event(subdir: str, event_id: str):
    event_id_safe = _safe_name(event_id)

    # 날짜 폴더는 event_id에 포함된 timestamp로 고정(덮어쓰기 안정)
    dt = _event_id_to_datetime(event_id_safe)
    if dt is None:
        dt = datetime.now()

    date_str = dt.strftime("%Y%m%d")
    folder = os.path.join(DATA_ROOT, subdir, date_str)
    ensure_dir(folder)

    # 파일명은 event_id 고정 -> 덮어쓰기
    return os.path.join(folder, f"{event_id_safe}.jpg")


# ─────────────────────────────────────────
# 경로 함수들
# - 앞으로는 event_id만 쓰는 게 목표
# - 하지만 기존 코드가 (dt, car_no)로 호출하는 것도 당분간 호환
# ─────────────────────────────────────────
def ws_car1_path(dt_or_event_id, car_no: str = None):
    if car_no is None:
        return _make_path_event("car1", dt_or_event_id)
    return _make_path_legacy("car1", dt_or_event_id, car_no)


def ws_leak1_path(dt_or_event_id, car_no: str = None):
    if car_no is None:
        return _make_path_event("WS_leak1", dt_or_event_id)
    return _make_path_legacy("WS_leak1", dt_or_event_id, car_no)


def ds_leak1_path(dt_or_event_id, car_no: str = None):
    if car_no is None:
        return _make_path_event("DS_leak1", dt_or_event_id)
    return _make_path_legacy("DS_leak1", dt_or_event_id, car_no)


def ws_leak2_path(dt_or_event_id, car_no: str = None):
    if car_no is None:
        return _make_path_event("WS_leak2", dt_or_event_id)
    return _make_path_legacy("WS_leak2", dt_or_event_id, car_no)


def ds_leak2_path(dt_or_event_id, car_no: str = None):
    if car_no is None:
        return _make_path_event("DS_leak2", dt_or_event_id)
    return _make_path_legacy("DS_leak2", dt_or_event_id, car_no)


def ws_wheel1_path(dt_or_event_id, car_no: str = None):
    if car_no is None:
        return _make_path_event("WS_wheel1", dt_or_event_id)
    return _make_path_legacy("WS_wheel1", dt_or_event_id, car_no)


def ds_wheel1_path(dt_or_event_id, car_no: str = None):
    if car_no is None:
        return _make_path_event("DS_wheel1", dt_or_event_id)
    return _make_path_legacy("DS_wheel1", dt_or_event_id, car_no)


def save_bgr_image_to_file(bgr, out_path: str) -> bool:
    """
    out_path가 같으면 덮어쓰기 된다.
    """
    if bgr is None or not out_path:
        return False

    dirpath = os.path.dirname(out_path)
    if dirpath:
        ensure_dir(dirpath)

    try:
        if isinstance(bgr, np.ndarray) and not bgr.flags["C_CONTIGUOUS"]:
            bgr = np.ascontiguousarray(bgr)

        ok = cv2.imwrite(out_path, bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return bool(ok)
    except Exception:
        return False
