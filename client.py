import zmq

def run_client():
    context = zmq.Context()
    socket = context.socket(zmq.REQ)
    
    print("서버에 연결 중...")
    socket.connect("tcp://localhost:5555")

    # 10번 요청 보내기
    for request in range(10):
        print(f"요청 전송 {request}...")
        socket.send(b"Hello")

        # 서버로부터 응답 대기 (Block)
        message = socket.recv()
        print(f"받은 응답 {request}: {message.decode('utf-8')}")

if __name__ == "__main__":
    run_client()