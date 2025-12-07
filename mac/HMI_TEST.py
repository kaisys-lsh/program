import zmq
import cv2
import numpy as np

# ─────────────────────────────────────────
# 보낼 때: PUSH_BIND = "tcp://*:5577"
# 받는 쪽에서는 sender IP를 넣어서 PULL
# 예: sender IP가 192.168.0.10 이면
#     "tcp://192.168.0.10:5577"
# ─────────────────────────────────────────
SENDER_ADDR = "tcp://172.30.1.33:5577"   # 테스트용(같은 PC일 때). 다른 PC면 IP 바꾸기.

def main():
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PULL)
    sock.connect(SENDER_ADDR)
    print(f"[RECV] connect to {SENDER_ADDR}")

    try:
        while True:
            # sender: sock.send_multipart([code_bytes, jpg_bytes])
            parts = sock.recv_multipart()
            if len(parts) != 2:
                print("[WARN] invalid message len:", len(parts))
                continue

            code_bytes, jpg_bytes = parts
            try:
                code = code_bytes.decode("utf-8") if code_bytes else ""
            except:
                code = ""

            # JPEG → 이미지로 디코딩
            jpg_array = np.frombuffer(jpg_bytes, dtype=np.uint8)
            frame = cv2.imdecode(jpg_array, cv2.IMREAD_COLOR)

            if frame is None:
                print("[WARN] failed to decode image")
                continue

            # 화면에 코드 출력
            if code:
                print(f"[RECV] code = '{code}'")
            else:
                print("[RECV] code = '' (empty)")

            # 이미지 창에 보여주기 (원하면 끄면 됨)
            cv2.imshow("HMI View", frame)
            # 'q' 누르면 종료
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()
        sock.close()
        ctx.term()


if __name__ == "__main__":
    main()
