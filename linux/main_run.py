# main_run.py
# --------------------------------------------------
# Entry point (얇게 유지)
# - Detectron2 setup
# - ZMQ sender start
# - SharedMemory open
# - Wheel watchers start (WS/DS)
# - Car number mode 실행 (IMAGE/VIDEO 선택)
# --------------------------------------------------

from config import config
from config.config import TEST_IMAGE_MODE

from setup.detectron_setup import setup_detectron
from utils.zmq_utils import ZmqSendWorker
from utils.shared_mem_utils import open_or_create_shm

from core.car_event_bus import CarEventBus
from core.wheel_flag_watcher import WheelFlagWatcher

# 너가 만든 통합 모드 래퍼
# (파일명이 mode/car_number_mode.py 라면 아래처럼)
from mode.number_mode import run_car_number_mode


def main():
    predictor, metadata, mark_class_idx = setup_detectron()

    # ZMQ 송신 워커
    sender = ZmqSendWorker()
    sender.start()

    # 이벤트 버스 (WS/DS 둘 다 같은 event_id 매칭)
    car_bus = CarEventBus(sender, pending_expire_sec=30.0)

    # 공유메모리 (WS / DS)
    shm_ws, shm_ws_buf = open_or_create_shm(config.SHM_WS_NAME, config.SHM_SIZE)
    print("[SHM] WS opened:", config.SHM_WS_NAME)

    shm_ds, shm_ds_buf = open_or_create_shm(config.SHM_DS_NAME, config.SHM_SIZE)
    print("[SHM] DS opened:", config.SHM_DS_NAME)

    # 휠 상태 watcher (기본: 1st/2nd 둘 다 모이면 1회 전송)
    ws_watcher = WheelFlagWatcher("WS", shm_ws_buf, car_bus, poll_interval=0.02, send_when_both=True)
    ds_watcher = WheelFlagWatcher("DS", shm_ds_buf, car_bus, poll_interval=0.02, send_when_both=True)
    ws_watcher.start()
    ds_watcher.start()

    try:
        print("[MAIN] IMAGE MODE" if TEST_IMAGE_MODE else "[MAIN] VIDEO MODE")

        run_car_number_mode(
            TEST_IMAGE_MODE,
            predictor,
            metadata,
            mark_class_idx,
            car_bus,
            shm_ws_buf,
            shm_ds_buf,
        )

    finally:
        print("[MAIN] shutdown")

        try:
            ws_watcher.stop()
            ds_watcher.stop()
        except Exception:
            pass

        try:
            sender.close()
        except Exception:
            pass

        try:
            if shm_ws is not None:
                shm_ws.close()
        except Exception:
            pass

        try:
            if shm_ds is not None:
                shm_ds.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
