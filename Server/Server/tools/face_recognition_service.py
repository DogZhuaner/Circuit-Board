import base64
import binascii
from pathlib import Path

import cv2
import numpy as np


class FaceRecognitionError(Exception):
    pass


SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
FACE_SIZE = (160, 160)


_cache_signature = None
_cache_model = None
_cache_labels = None
_face_cascade = None


def _get_face_cascade():
    global _face_cascade
    if _face_cascade is None:
        cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(str(cascade_path))
        if cascade.empty():
            raise FaceRecognitionError(f"无法加载 OpenCV 人脸检测模型: {cascade_path}")
        _face_cascade = cascade
    return _face_cascade


def _decode_data_url(image_data):
    image_data = str(image_data or "").strip()
    if not image_data:
        raise FaceRecognitionError("缺少人脸图片")

    if "," in image_data and image_data.lower().startswith("data:image/"):
        image_data = image_data.split(",", 1)[1]

    try:
        raw = base64.b64decode(image_data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise FaceRecognitionError(f"图片 base64 解码失败: {exc}") from exc

    image_array = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise FaceRecognitionError("无法解析上传的人脸图片")
    return image


def _load_image_file(path):
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FaceRecognitionError(f"无法读取人脸库图片: {path}")
    return image


def _largest_face(gray):
    cascade = _get_face_cascade()
    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=4,
        minSize=(50, 50),
    )
    if len(faces) == 0:
        return None
    return max(faces, key=lambda item: item[2] * item[3])


def _center_crop(gray):
    height, width = gray.shape[:2]
    side = min(width, height)
    x = max((width - side) // 2, 0)
    y = max((height - side) // 2, 0)
    return gray[y:y + side, x:x + side]


def _preprocess_face(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    face_box = _largest_face(gray)
    if face_box is not None:
        x, y, width, height = face_box
        margin_x = int(width * 0.18)
        margin_y = int(height * 0.22)
        x1 = max(x - margin_x, 0)
        y1 = max(y - margin_y, 0)
        x2 = min(x + width + margin_x, gray.shape[1])
        y2 = min(y + height + margin_y, gray.shape[0])
        face = gray[y1:y2, x1:x2]
    else:
        face = _center_crop(gray)

    if face.size == 0:
        raise FaceRecognitionError("未能提取有效人脸区域")

    face = cv2.resize(face, FACE_SIZE)
    face = cv2.equalizeHist(face)
    return face


def _list_face_files(face_library_dir):
    face_dir = Path(face_library_dir)
    if not face_dir.exists():
        raise FaceRecognitionError(f"人脸库目录不存在: {face_dir}")
    if not face_dir.is_dir():
        raise FaceRecognitionError(f"人脸库路径不是目录: {face_dir}")

    files = [
        path for path in sorted(face_dir.iterdir())
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    ]
    if not files:
        raise FaceRecognitionError(f"人脸库目录中没有图片: {face_dir}")
    return files


def _build_signature(files):
    return tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in files)


def _build_model(face_library_dir):
    files = _list_face_files(face_library_dir)
    signature = _build_signature(files)

    global _cache_signature, _cache_model, _cache_labels
    if signature == _cache_signature and _cache_model is not None and _cache_labels is not None:
        return _cache_model, _cache_labels

    if not hasattr(cv2, "face") or not hasattr(cv2.face, "LBPHFaceRecognizer_create"):
        raise FaceRecognitionError("当前 OpenCV 缺少 cv2.face，请安装 opencv-contrib-python-headless")

    samples = []
    labels = {}
    for index, path in enumerate(files):
        image = _load_image_file(path)
        samples.append(_preprocess_face(image))
        labels[index] = {
            "user_no": path.stem,
            "filename": path.name,
            "path": str(path),
        }

    model = cv2.face.LBPHFaceRecognizer_create(radius=1, neighbors=8, grid_x=8, grid_y=8)
    model.train(samples, np.array(list(labels.keys()), dtype=np.int32))

    _cache_signature = signature
    _cache_model = model
    _cache_labels = labels
    return model, labels


def recognize_face_image(image_data, face_library_dir, match_threshold):
    model, labels = _build_model(face_library_dir)
    query_image = _decode_data_url(image_data)
    query_face = _preprocess_face(query_image)

    label, distance = model.predict(query_face)
    matched = labels.get(int(label))
    if not matched:
        raise FaceRecognitionError("未找到匹配的人脸库标签")

    threshold = float(match_threshold)
    similarity = max(0.0, min(1.0, 1.0 - (float(distance) / threshold)))
    return {
        "matched": float(distance) <= threshold,
        "user_no": matched["user_no"],
        "filename": matched["filename"],
        "distance": float(distance),
        "similarity": round(similarity, 4),
        "threshold": threshold,
    }
