import cv2
import numpy as np
import ffmpeg
import time
from datetime import datetime
import sys

# ==========================================
# [설정]
# ==========================================
RTSP_URL = "rtsp://127.0.0.1:8554/test"
WIDTH    = 640
HEIGHT   = 480
# [변경] VLC가 1fps는 '정지화면'으로 착각할 수 있어 5fps로 올림
FPS      = 5.0   

def main():
    print(f"[*] RTSP 송출 시작")
    print(f"[*] 주소: {RTSP_URL}")
    print("[*] 설정: GOP=1 (즉시 로딩), yuv420p (호환성)")

    # 1. FFmpeg 파이프라인 설정
    process_args = (
        ffmpeg
        .input('pipe:', format='rawvideo', pix_fmt='bgr24', s=f'{WIDTH}x{HEIGHT}', r=FPS)
        .output(
            RTSP_URL,
            format='rtsp',
            vcodec='libx264',
            pix_fmt='yuv420p',    # VLC 필수
            preset='ultrafast',
            tune='zerolatency',
            rtsp_transport='tcp', # TCP 강제
            g=1,                  # [핵심 해결책] 매 프레임마다 키프레임 전송 (대기 시간 0초)
            keyint_min=1          # 최소 키프레임 간격 1
        )
        .overwrite_output()
    )

    # 2. 프로세스 시작
    process = process_args.run_async(pipe_stdin=True, quiet=True) # quiet=True로 로그 좀 줄임

    try:
        print("[*] 전송 중... VLC를 켜보세요.")
        while True:
            start_time = time.time()

            # 3. 화면 생성
            frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
            cv2.rectangle(frame, (0,0), (WIDTH-5, HEIGHT-5), (0, 255, 0), 5) # 초록 테두리
            
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            font = cv2.FONT_HERSHEY_SIMPLEX
            (text_w, text_h), _ = cv2.getTextSize(now, font, 1.0, 2)
            x = (WIDTH - text_w) // 2
            y = (HEIGHT + text_h) // 2
            
            cv2.putText(frame, now, (x, y), font, 1.0, (255, 255, 255), 2)
            
            # FPS 확인용 원 (움직임)
            cx = int(x + (time.time() * 50) % 200)
            cv2.circle(frame, (cx, 50), 10, (0, 255, 255), -1)

            # 4. 전송
            try:
                process.stdin.write(frame.tobytes())
                process.stdin.flush()
            except BrokenPipeError:
                print("\n[오류] 서버 연결 끊김.")
                break
            except Exception as e:
                print(f"\n[오류] {e}")
                break

            # 5. FPS 대기
            elapsed = time.time() - start_time
            delay = (1.0 / FPS) - elapsed
            if delay > 0:
                time.sleep(delay)
            
            # print(f"Sent: {now}")

    except KeyboardInterrupt:
        print("종료합니다.")
    finally:
        if process:
            process.stdin.close()
            process.wait()

if __name__ == "__main__":
    main()