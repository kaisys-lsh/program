# utils/image_utils.py
# --------------------------------------------------
# 이미지 파일 관련 유틸 함수
# --------------------------------------------------

import os
import re
import glob


def numeric_sort_key(path):
    """
    파일 이름에 들어 있는 숫자 기준으로 정렬하기 위한 함수.
    예) frame_1.jpg, frame_2.jpg, frame_10.jpg ...
    숫자가 없으면 파일 이름 문자열 그대로 사용.
    """
    name = os.path.basename(path)
    match = re.search(r"\d+", name)

    if match is not None:
        try:
            return int(match.group())
        except ValueError:
            # 숫자로 변환이 안 되면 그냥 문자열 사용
            pass

    return name


def get_image_paths(image_dir):
    """
    디렉토리 안의 이미지 파일 목록을 가져와서
    숫자 기준으로 정렬하여 리스트로 반환.
    (확장자: .jpg, .jpeg, .png, .bmp)
    """
    # 디렉토리 안 모든 파일 경로 가져오기
    pattern = os.path.join(image_dir, "*")
    all_paths = glob.glob(pattern)

    # 지원하는 확장자
    valid_exts = [".jpg", ".jpeg", ".png", ".bmp"]

    image_paths = []

    # 하나씩 돌면서 이미지 확장자만 골라내기
    idx = 0
    while idx < len(all_paths):
        path = all_paths[idx]
        _, ext = os.path.splitext(path)
        ext_lower = ext.lower()

        is_valid = False
        i = 0
        while i < len(valid_exts):
            if ext_lower == valid_exts[i]:
                is_valid = True
                break
            i = i + 1

        if is_valid:
            image_paths.append(path)

        idx = idx + 1

    # 숫자 기준 정렬
    image_paths.sort(key=numeric_sort_key)

    return image_paths
