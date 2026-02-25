import zmq

def start_push_pull_server():
    context = zmq.Context()

    # 1. 클라이언트로부터 데이터를 받는 소켓 (PULL)
    receiver = context.socket(zmq.PULL)
    receiver.bind("tcp://*:5557")

    # 2. 클라이언트에게 데이터를 보내는 소켓 (PUSH)
    sender = context.socket(zmq.PUSH)
    sender.bind("tcp://*:5558")

    print("서버가 준비되었습니다. (PULL: 5557 / PUSH: 5558)")

    while True:
        # 클라이언트로부터 메시지 수신
        message = receiver.recv_string()
        print(f"수신된 메시지: {message}")

        # 간단한 영문 변환 (대문자 변환)
        translated = f"{message.upper()} (Processed by Server)"

        # 클라이언트에게 결과 전송
        print(f"결과 전송 중: {translated}")
        sender.send_string(translated)

if __name__ == "__main__":
    start_push_pull_server()