import zmq

def start_dual_echo_server():
    context = zmq.Context()

    # 1. 첫 번째 서버 소켓 설정
    server1 = context.socket(zmq.REP)
    server1.bind("tcp://*:7775")

    # 2. 두 번째 서버 소켓 설정
    server2 = context.socket(zmq.REP)
    server2.bind("tcp://*:7776")

    # 3. 두 소켓을 동시에 감시하기 위한 Poller 설정
    poller = zmq.Poller()
    poller.register(server1, zmq.POLLIN)
    poller.register(server2, zmq.POLLIN)

    print("서버가 시작되었습니다.")

    while True:
        try:
            # 소켓으로부터 이벤트가 발생할 때까지 대기
            sockets = dict(poller.poll())

            if server1 in sockets:
                image_data = server1.recv()
                server1.send(image_data)  
                print(f"1: 이미지 수신 및 반환 완료")

            if server2 in sockets:
                image_data = server2.recv()
                server2.send(image_data)  
                print("2: 이미지 수신 및 반환 완료")

        except KeyboardInterrupt:
            break

    # 자원 해제
    server1.close()
    server2.close()
    context.term()

if __name__ == "__main__":
    start_dual_echo_server()