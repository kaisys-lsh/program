# Ubuntu 22.04 + CUDA 11.8 + cuDNN
FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

# 기본 패키지 설치 (Python 3.10은 Ubuntu 22.04 기본)
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv python3-dev \
    git build-essential cmake \
    libgl1-mesa-dev libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# python → python3 링크 (편의를 위해)
RUN ln -s /usr/bin/python3 /usr/bin/python || true

# pip 업그레이드
RUN python -m pip install --upgrade pip

# ---- 파이썬 패키지 버전 고정 ----
# numpy는 PyTorch 2.5.1 / Python 3.10과 궁합 좋은 1.26.4로 고정
RUN pip install \
    numpy==1.26.4

# PyTorch 2.5.1 + cu118 (공식 cu118 index 사용)
RUN pip install \
    torch==2.5.1 \
    torchvision==0.20.1 \
    torchaudio==2.5.1 \
    --index-url https://download.pytorch.org/whl/cu118

# 자주 쓰는 패키지들 (필요시 더 추가 가능)
RUN pip install \
    opencv-python \
    matplotlib \
    tqdm \
    yacs \
    termcolor \
    tabulate \
    pyzmq \
    pymysql

# Detectron2를 Git에서 설치 (소스 빌드)
RUN pip install --no-build-isolation 'git+https://github.com/facebookresearch/detectron2.git'

# ⬇⬇⬇ 여기만 추가: 마지막에 numpy 버전 최종 고정
RUN pip install numpy==1.26.4

# 작업 디렉토리
WORKDIR /workspace

# 컨테이너 들어갔을 때 기본 쉘
CMD ["/bin/bash"]
