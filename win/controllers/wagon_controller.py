# controllers/wagon_controller.py
# --------------------------------------------------
# 대차 이벤트 컨트롤러 (수정본: car_no를 END로 처리)
#
# ✅ 변경점(요청사항)
# - END 이벤트가 따로 안 오는 구조이므로,
#   on_car_no() 수신 시점을 "사실상 END"로 보고 _handle_end(event_id) 호출
#
# 나머지:
# - WheelFlagWatcher/CarEventBus wheel_status payload 형식 그대로 대응
# - dB 피크 추적 (zone1/zone2)
# - END 후 상태 리셋
# - frame/peak frame copy()로 안전하게 보관
# --------------------------------------------------

from datetime import datetime

from utils.image_utils import save_bgr_image
from utils.wheel_status_utils import judge_one_wheel


class WagonController:
    def __init__(self, enqueue_db_patch, delay_count=7):
        self.enqueue_db_patch = enqueue_db_patch
        self.delay_count = int(delay_count)

        self.current_event_id = None
        self.current_seq_no = 0

        # cam_id -> bgr (최신 프레임)
        self.latest_frames = {}

        # cam_id -> {"db": float, "frame": bgr}
        self.zone1_peak = {}
        self.zone2_peak = {}

    # --------------------------------------------------
    # Frame / dB
    # --------------------------------------------------
    def update_latest_frame(self, cam_id, bgr):
        """
        cam_id: 예) "cam", "ws1", "ds1", "ws2", "ds2" 등
        bgr: OpenCV BGR 이미지
        """
        if bgr is None:
            return

        # 버퍼 재사용/오버레이 등으로 내용이 변할 수 있어 copy() 권장
        try:
            self.latest_frames[cam_id] = bgr.copy()
        except Exception:
            self.latest_frames[cam_id] = bgr

    def on_db(self, cam_id, value):
        """
        dB 입력 → 피크 프레임 추적
        zone 구분:
          - zone1: ws1/ds1
          - zone2: 그 외(= ws2/ds2 등)
        """
        if not self.current_event_id:
            return

        zone = "zone1" if cam_id in ("ws1", "ds1") else "zone2"
        peak = self.zone1_peak if zone == "zone1" else self.zone2_peak

        prev = peak.get(cam_id)
        try:
            v = float(value)
        except Exception:
            return

        if prev is None or v > float(prev.get("db", -1e9)):
            frame = self.latest_frames.get(cam_id)
            if frame is not None:
                try:
                    peak[cam_id] = {"db": v, "frame": frame.copy()}
                except Exception:
                    peak[cam_id] = {"db": v, "frame": frame}

    # --------------------------------------------------
    # ZMQ 이벤트 (CarEventBus 기준)
    # --------------------------------------------------
    def on_car_event(self, data: dict):
        """
        data 예:
          {"type":"car_event","event":"START","car_no":None,"event_id":...}
          {"type":"car_event","event":"END","car_no":"057","event_id":...}  (옵션/호환)
        """
        if not isinstance(data, dict):
            return

        ev = data.get("event")
        event_id = data.get("event_id")

        if ev == "START":
            self._handle_start(event_id)
        elif ev == "END":
            # 혹시 END가 따로 오는 구형 호환도 남겨둠
            self._handle_end(event_id)

    def on_car_no(self, data: dict):
        """
        ✅ 현재 운영 로그 형태:
          START (car_event) → car_no (바로 들어옴) → (END 이벤트 없음)
        따라서 car_no 수신 시점을 END로 보고 _handle_end(event_id)까지 처리한다.

        data 예:
          {"type":"car_no","event_id":...,"car_no":"175","ts_ms":...}
        """
        if not isinstance(data, dict):
            return

        event_id = data.get("event_id")
        car_no = str(data.get("car_no", "")).strip()

        if not event_id or not car_no:
            return

        # START가 먼저 안 왔거나 순서가 꼬였을 때 안전장치
        if not self.current_event_id:
            self.current_event_id = event_id

        # 1) car_no patch
        self.enqueue_db_patch({
            "event_id": event_id,
            "car_no": car_no,
            "car_no_done": 1,
        })

        # 2) ✅ car_no를 END로 처리
        self._handle_end(event_id)

    def on_wheel_status(self, data: dict):
        """
        WheelFlagWatcher/CarEventBus payload 직접 대응

        data 예:
        {
          "type":"wheel_status",
          "pos":"WS" or "DS",
          "car_no":"090",
          "stop_flag":0/1,
          "wheel1_rotation":int,
          "wheel1_position":int,
          "wheel2_rotation":int,
          "wheel2_position":int,
          "event_id":... (car_no 매핑되면 CarEventBus가 붙여줌)
        }
        """
        if not isinstance(data, dict):
            return

        # event_id가 붙어오면 그걸 최우선 사용 (정합성)
        event_id = data.get("event_id")
        if not event_id:
            # event_id가 없으면 "현재 이벤트"에 붙여보되, 없으면 포기
            if not self.current_event_id:
                return
            event_id = self.current_event_id

        pos = str(data.get("pos", "")).strip().lower()  # "ws"/"ds"
        if pos not in ("ws", "ds"):
            pos = "ws"

        w1 = {
            "rotation": data.get("wheel1_rotation", 0),
            "position": data.get("wheel1_position", 0),
            "stop_flag": data.get("stop_flag", 0),
        }
        w2 = {
            "rotation": data.get("wheel2_rotation", 0),
            "position": data.get("wheel2_position", 0),
            "stop_flag": data.get("stop_flag", 0),
        }

        st1 = judge_one_wheel(w1)
        st2 = judge_one_wheel(w2)

        patch = {
            "event_id": event_id,
            f"{pos}_wheel1_status": st1,
            f"{pos}_wheel2_status": st2,
            f"wheel_{pos}_done": 1,
        }
        self.enqueue_db_patch(patch)

    # --------------------------------------------------
    # START / END
    # --------------------------------------------------
    def _handle_start(self, event_id: str):
        if not event_id:
            return

        self.current_event_id = event_id
        self.current_seq_no += 1

        self.zone1_peak.clear()
        self.zone2_peak.clear()

        patch = {
            "event_id": event_id,
            "seq_no": self.current_seq_no,
            "start_done": 1,
            "ts": datetime.now(),
        }

        # START 시점 스냅샷 저장
        for cam_id, bgr in self.latest_frames.items():
            path = save_bgr_image(event_id, bgr, f"img_{cam_id}")
            if path:
                patch[f"img_{cam_id}_path"] = path

        self.enqueue_db_patch(patch)

    def _handle_end(self, event_id: str):
        """
        zone1: 현재 이벤트(event_id)에 저장/patch
        zone2: seq_no 지연 매칭으로 과거 row에 patch (seq_no 기준 업데이트)

        ⚠️ 참고:
        zone2 저장 폴더 키를 event_id로 쓰는 동작은 기존 유지.
        (원하면 delayed_seq의 event_id를 찾아서 저장하는 방식으로 개선 가능)
        """
        if not event_id:
            return

        # zone1 (현재 event)
        patch = {"event_id": event_id}

        for cam_id, info in self.zone1_peak.items():
            name = f"img_{cam_id}"
            path = save_bgr_image(event_id, info.get("frame"), name)
            patch[f"{cam_id}_db"] = info.get("db", 0)
            patch[f"{name}_path"] = path

        patch["zone1_done"] = 1
        self.enqueue_db_patch(patch)

        # zone2 (지연 매칭)
        if self.delay_count > 0:
            delayed_seq = self.current_seq_no - (self.delay_count - 1)
            if delayed_seq > 0:
                patch2 = {"seq_no": delayed_seq}

                for cam_id, info in self.zone2_peak.items():
                    name = f"img_{cam_id}"
                    path = save_bgr_image(event_id, info.get("frame"), name)
                    patch2[f"{cam_id}_db"] = info.get("db", 0)
                    patch2[f"{name}_path"] = path

                patch2["zone2_done"] = 1
                self.enqueue_db_patch(patch2)

        # ✅ 종료 후 상태 리셋 (다음 이벤트 섞임 방지)
        self.current_event_id = None
        self.zone1_peak.clear()
        self.zone2_peak.clear()
