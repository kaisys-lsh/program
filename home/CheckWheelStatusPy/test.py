# ws_test_recv_multi.py
# 3개의 ZMQ PULL 소켓에서 WS 영상 + 상태를 동시에 수신/표시

import zmq
import cv2
import numpy as np
import json

# 🔹 여기서 3개 소켓(포트)을 정의
#   서버(영상 보내는 프로그램)가 bind 하고,
#   HMI는 여기에 connect 하는 구조
STREAMS = [
    ("cma1", "tcp://172.30.1.67:5577"),  # 첫 번째 영상
    ("WS",   "tcp://172.30.1.67:5578"),  # 두 번째 영상
    ("DS",   "tcp://172.30.1.67:5579"),  # 세 번째 영상
]


def main():
    ctx = zmq.Context.instance()
    poller = zmq.Poller()
    sockets = {}  # socket -> stream_name

    # 1) 3개 PULL 소켓 connect + poller 등록  ✅ 여기만 바뀜
    for name, addr in STREAMS:
        sock = ctx.socket(zmq.PULL)
        sock.connect(addr)  # ← bind 대신 connect
        sockets[sock] = name
        poller.register(sock, zmq.POLLIN)
        print(f"[WS-RECV] {name} connect: {addr}")

    print("[WS-RECV] 3개 WS 영상/상태 수신 대기중...")

    created_windows = set()

    try:
        while True:
            events = dict(poller.poll(10))

            for sock, flag in events.items():
                if not (flag & zmq.POLLIN):
                    continue

                stream_name = sockets[sock]

                # 메시지 수신: [frame_bytes, json_bytes]
                parts = sock.recv_multipart()
                if len(parts) != 2:
                    print(f"[{stream_name}] 잘못된 메시지 파트 수:", len(parts))
                    continue

                frame_bytes, meta_bytes = parts

                # 2-1) JSON 상태 출력
                try:
                    meta = json.loads(meta_bytes.decode("utf-8"))
                    print(f"[{stream_name}] META:", meta)
                except Exception as e:
                    print(f"[{stream_name}] JSON 파싱 오류:", e)

                # 2-2) JPEG → BGR 이미지 디코드
                if frame_bytes:
                    npbuf = np.frombuffer(frame_bytes, np.uint8)
                    img = cv2.imdecode(npbuf, cv2.IMREAD_COLOR)
                    if img is not None:
                        win_name = f"WS RECV - {stream_name}"

                        if win_name not in created_windows:
                            cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
                            created_windows.add(win_name)

                        cv2.imshow(win_name, img)
                    else:
                        print(f"[{stream_name}] imdecode 실패")
                else:
                    print(f"[{stream_name}] 빈 frame_bytes 수신")

            if cv2.waitKey(1) & 0xFF == 27:
                print("[WS-RECV] ESC 입력, 종료")
                break

    finally:
        cv2.destroyAllWindows()
        for sock in sockets.keys():
            sock.close()
        ctx.term()


if __name__ == "__main__":
    main()
