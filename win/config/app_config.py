# config/app_config.py
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_PATH = os.path.join(BASE_DIR, "ui", "window_hmi.ui")

# ----------------------------
# 개발/테스트 옵션
# ----------------------------
USE_DUMMY_CRY = True
USE_DUMMY_CAMERA = True

# ----------------------------
# Zone2 매칭 오프셋
# - "큐 지연"이 아니라, zone2 결과가 몇 대 앞(=몇 seq_no 앞) 대차에 귀속되는지
# - 실제 설계가 7대 지연이면 7로 고정
# ----------------------------
DELAY_COUNT = 7

# ----------------------------
# UI 표시 정책
# - True: DB에 모든 데이터가 완성된 row만 HMI에 표시
# ----------------------------
SHOW_ONLY_DB_COMPLETE = True

# ----------------------------
# DB 폴링 주기 (완성 row 조회)
# - 너무 빠르면 DB부하, 너무 느리면 UI 반응 느림
# ----------------------------
DB_POLL_INTERVAL_SEC = 0.2

# ----------------------------
# 테이블 최대 행
# ----------------------------
MAX_TABLE_ROWS = 172

# ----------------------------
# START 스냅샷 저장 지연
# - START 들어왔는데 프레임이 아직 없을 수 있어서 잠깐 대기 후 저장
# ----------------------------
SNAPSHOT_SEC = 1.0

# ----------------------------
# 라이브 영상 표시
# - False면 저장된 이미지/DB기반 화면만 사용 (CPU 절약)
# ----------------------------
SHOW_LIVE_VIDEO = False

# ----------------------------
# ZMQ 시작 시 과거 메시지 쏟아짐 방어 (선택)
# - DB 기반 표시로 바꾸면 영향이 줄지만, 로그/내부상태 꼬임 방어용
# ----------------------------
ZMQ_DROP_OLD_MESSAGES_ON_START = True
ZMQ_START_GRACE_MS = 500
