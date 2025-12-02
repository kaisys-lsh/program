import cv2
import os
import matplotlib.pyplot as plt
from detectron2.engine import DefaultPredictor
from detectron2.config import get_cfg
from detectron2 import model_zoo
from detectron2.utils.visualizer import Visualizer
from detectron2.data import MetadataCatalog

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 그 폴더 안의 test.jpg 경로
IMAGE_PATH = os.path.join(BASE_DIR, "test.jpg")

# Config 불러오기
cfg = get_cfg()
cfg.merge_from_file(
    model_zoo.get_config_file(
        "COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml"
    )
)
cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = 0.5
cfg.MODEL.WEIGHTS = model_zoo.get_checkpoint_url(
    "COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml"
)

# Predictor 생성
cfg.MODEL.DEVICE = "cpu"
predictor = DefaultPredictor(cfg)

# 이미지 읽기
img = cv2.imread(IMAGE_PATH)
assert img is not None, f"이미지를 찾을 수 없음: {IMAGE_PATH}"

# 추론
outputs = predictor(img)

instances = outputs["instances"].to("cpu")

classes = instances.pred_classes
scores = instances.scores
boxes = instances.pred_boxes
masks = instances.pred_masks  # mask_rcnn이면 존재

# 시각화
v = Visualizer(
    img[:, :, ::-1],
    MetadataCatalog.get(cfg.DATASETS.TRAIN[0]),
    scale=1.0
)
out = v.draw_instance_predictions(outputs["instances"].to("cpu"))

result_img = out.get_image()  # RGB

# 저장 경로: image.py가 있는 폴더 안에 result.jpg
OUTPUT_PATH = os.path.join(BASE_DIR, "result.jpg")

# BGR로 바꿔서 저장 (cv2는 BGR 기준)
cv2.imwrite(OUTPUT_PATH, result_img[:, :, ::-1])

print(f"저장 완료: {OUTPUT_PATH}")
