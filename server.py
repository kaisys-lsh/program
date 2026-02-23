import time
import zmq

def run_server():
    context = zmq.Context()
    socket = context.socket(zmq.REP)
    socket.bind("tcp://*:5555")  # 5555 포트 바인딩

    print("서버가 시작되었습니다...")

    while True:
        # 클라이언트의 요청 대기 (Block)
        message = socket.recv()
        print(f"받은 요청: {message.decode('utf-8')}")

        # 어떤 작업을 수행하는 척 (1초 대기)
        time.sleep(1)

        # 클라이언트에게 응답 전송
        socket.send(b"World")

if __name__ == "__main__":
    run_server()