import zmq
import time

def start_push_pull_client():
    context = zmq.Context()

    # 1. 서버로 데이터를 보내는 소켓 (PUSH)
    sender = context.socket(zmq.PUSH)
    sender.connect("tcp://localhost:5557")

    # 2. 서버로부터 데이터를 받는 소켓 (PULL)
    receiver = context.socket(zmq.PULL)
    receiver.connect("tcp://localhost:5558")

    print("클라이언트가 준비되었습니다. 메시지를 입력하세요.")

    while True:
        user_input = input("입력: ")
        if user_input.lower() == 'exit':
            break

        # 서버로 전송
        sender.send_string(user_input)

        # 서버로부터 결과 수신
        result = receiver.recv_string()
        print(f"서버로부터 받은 결과: {result}\n")

if __name__ == "__main__":
    start_push_pull_client()