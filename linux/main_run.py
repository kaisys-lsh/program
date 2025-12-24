# main_run.py
# --------------------------------------------------
# Entry point (얇게 유지)
# - Detectron2 setup
# - ZMQ sender start
# - SharedMemory open
# - Wheel watchers start (WS/DS)
# - Car number mode 실행 (IMAGE/VIDEO 선택)
#
# 이번 수정 반영
# - CarEventBus: START에서 event_id 생성, car_no 확정/휠상태 매칭은 bus가 담당
# - number_mode: car_bus.send_start(), car_bus.send_car_no() 사용
# - watcher: car_bus.on_wheel_status(payload) 로 보고
# --------------------------------------------------

from config.config import TEST_IMAGE_MODE, PUSH_BIND
from setup.detectron_setup import setup_detectron
from utils.zmq_utils import ZmqSendWorker
from utils.shared_mem_utils import open_or_create_shm

from core.car_event_bus import CarEventBus
from core.wheel_flag_watcher import WheelFlagWatcher

from mode.car_number_mode import run_car_number_mode

# (선택) SHM 구조 모니터링이 필요하면 주석 해제
# from utils.shm_debug import ShmMonitorThread


def main():
    # -----------------------------
    # 1) Detectron2 Predictor 준비
    # -----------------------------
    predictor, metadata, mark_class_idx = setup_detectron()

    # -----------------------------
    # 2) ZMQ Sender 시작
    # -----------------------------
    zmq_sender = ZmqSendWorker(bind_addr=PUSH_BIND)
    zmq_sender.start()

    # -----------------------------
    # 3) SharedMemory attach/create
    # -----------------------------
    shm, shm_array = open_or_create_shm()

    # (선택) SHM 구조 자체를 주기적으로 보고 싶으면 켜기
    # mon = ShmMonitorThread(shm_array, interval_sec=0.5)
    # mon.start()

    # -----------------------------
    # 4) Event Bus
    # -----------------------------
    car_bus = CarEventBus(zmq_sender)

    # -----------------------------
    # 5) Wheel Watchers (WS/DS)
    #    - 같은 shm_array를 공유
    # -----------------------------
    ws_watcher = WheelFlagWatcher(
        "WS",
        shm_array,
        car_bus,
        poll_interval=0.02,
        send_when_both=True,
    )
    ds_watcher = WheelFlagWatcher(
        "DS",
        shm_array,
        car_bus,
        poll_interval=0.02,
        send_when_both=True,
    )

    ws_watcher.start()
    ds_watcher.start()

    # -----------------------------
    # 6) Car number mode 실행
    # -----------------------------
    try:
        run_car_number_mode(
            use_image_mode=TEST_IMAGE_MODE,
            predictor=predictor,
            metadata=metadata,
            mark_class_idx=mark_class_idx,
            car_bus=car_bus,
            shm_array=shm_array,
        )
    except KeyboardInterrupt:
        print("[MAIN] KeyboardInterrupt")
    finally:
        # -----------------------------
        # 종료 처리
        # -----------------------------
        try:
            ws_watcher.stop()
        except Exception:
            pass
        try:
            ds_watcher.stop()
        except Exception:
            pass

        try:
            zmq_sender.stop()
        except Exception:
            pass

        try:
            shm.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
