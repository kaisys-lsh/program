# detectron_setup.py
# --------------------------------------------------
# Detectron2 관련 설정, 모델 로드
# --------------------------------------------------

import torch

from detectron2.config import get_cfg
from detectron2.engine import DefaultPredictor
from detectron2.data import MetadataCatalog
from detectron2.projects import point_rend

from config import config 


def setup_detectron():
    """
    Detectron2 설정을 만들고, 가중치를 로드한 뒤
    predictor, metadata, mark_class_idx 를 반환한다.
    """
    cfg = get_cfg()
    point_rend.add_pointrend_config(cfg)
    cfg.merge_from_file(config.CFG_PATH)
    cfg.MODEL.WEIGHTS = config.WEIGHTS_PATH

    # 입력 크기 설정 (원래 코드와 동일)
    cfg.INPUT.MIN_SIZE_TEST = 720
    cfg.INPUT.MAX_SIZE_TEST = 1280

    # 클래스 개수 (0~10 → 11개)
    cfg.MODEL.ROI_HEADS.NUM_CLASSES = 11
    cfg.MODEL.POINT_HEAD.NUM_CLASSES = 11

    # 점수 임계값
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = 0.8

    # 디바이스 설정
    cfg.MODEL.DEVICE = config.get_device()

    metadata = None
    mark_class_idx = None

    # 학습할 때 저장한 메타데이터가 있으면 로드
    try:
        ckpt = torch.load(config.WEIGHTS_PATH, map_location="cpu")
        meta_name = "inference_meta_pointrend_numbers"

        if "metadata" in ckpt:
            MetadataCatalog.get(meta_name).set(**ckpt["metadata"])

        metadata = MetadataCatalog.get(meta_name)

        # thing_classes 안에서 "mark" 클래스의 index 찾기
        if metadata is not None and hasattr(metadata, "thing_classes"):
            idx = 0
            while idx < len(metadata.thing_classes):
                name = str(metadata.thing_classes[idx]).lower()
                if name == "mark":
                    mark_class_idx = idx
                    print("[META] mark class idx =", mark_class_idx)
                    break
                idx += 1

    except Exception as e:
        print("[WARN] metadata load failed:", e)
        metadata = None

    predictor = DefaultPredictor(cfg)
    return predictor, metadata, mark_class_idx
