import zmq
import os

def run_test_client(send_path, save_dir, ports=["7775", "7776"]):
    context = zmq.Context()
    
    # 저장할 디렉토리가 없으면 생성합니다.
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    for port in ports:
        print(f"--- Port {port} 테스트 시작 ---")
        socket = context.socket(zmq.REQ)
        socket.connect(f"tcp://localhost:{port}")

        try:
            # 1. 전송할 이미지 파일 읽기
            with open(send_path, "rb") as f:
                send_data = f.read()
            
            print(f"[{port}] 이미지 전송 중... (원본 경로: {send_path})")
            socket.send(send_data)

            # 2. 서버로부터 에코 이미지 수신
            received_data = socket.recv()

            # 3. 받은 이미지 저장 (파일명에 포트 번호 추가)
            save_path = os.path.join(save_dir, f"mirrored_from_{port}.jpg")
            with open(save_path, "wb") as f:
                f.write(received_data)
            
            print(f"[{port}] 수신 완료 및 저장 성공: {save_path}")

        except Exception as e:
            print(f"[{port}] 오류 발생: {e}")
        
        finally:
            socket.close()

    context.term()
    print("\n모든 테스트가 완료되었습니다.")

if __name__ == "__main__":
    # --- 설정 영역 ---
    IMAGE_TO_SEND = "095406_234.jpg"      # 서버로 보낼 이미지 경로
    DIR_TO_SAVE = "./received_images"      # 서버에서 돌려받은 이미지를 저장할 폴더
    # ----------------
    
    run_test_client(IMAGE_TO_SEND, DIR_TO_SAVE)