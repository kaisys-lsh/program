import zmq
import cv2
import numpy as np

PULL_ADDR = "tcp://192.168.0.103:5577"  # sender가 tcp://*:5577 로 bind하므로 동일 포트로 접속

def main():
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PULL)
    sock.connect(PULL_ADDR)
    
    print("[RECEIVER] Waiting for frames...")

    while True:
        try:
            # 송신 메시지 형식: [code_bytes, jpg_bytes]
            code_bytes, jpg_bytes = sock.recv_multipart()

            code_str = code_bytes.decode("utf-8") if code_bytes else ""
            nparr = np.frombuffer(jpg_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if img is None:
                print("[WARN] Failed to decode image")
                continue

            # 화면에 코드 표시
            cv2.putText(img, f"CODE: {code_str}",
                        (30, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.3,
                        (0, 0, 255), 3)

            cv2.imshow("ZMQ Receiver", img)

            key = cv2.waitKey(1)
            if key == 27:   # ESC 종료
                break

        except KeyboardInterrupt:
            break

    cv2.destroyAllWindows()
    sock.close()
    ctx.term()


if __name__ == "__main__":
    main()
