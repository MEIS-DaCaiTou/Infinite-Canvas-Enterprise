"""Local foreground masks. No model download, credentials or asset writes at startup."""
import base64
import io
import os
from functools import lru_cache
from pathlib import Path
from threading import Lock

from PIL import Image, ImageOps

_inference_lock = Lock()


def model_path():
    return Path(os.environ.get('ICE_SEGMENTATION_MODEL') or Path(__file__).resolve().parents[1] / 'models' / 'isnet-general-use.onnx')


@lru_cache(maxsize=1)
def _session(path):
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    return ort.InferenceSession(str(path), options, providers=['CPUExecutionProvider'])


def predict_mask(image, session):
    import numpy as np
    # IS-Net general-use input/output convention from rembg's DIS session.
    pixels = np.asarray(image.convert('RGB').resize((1024, 1024), Image.Resampling.LANCZOS), dtype=np.float32)
    pixels = pixels / max(float(pixels.max()), 1.0) - .5
    inputs = np.transpose(pixels, (2, 0, 1))[None, ...]
    result = np.asarray(session.run(None, {session.get_inputs()[0].name: inputs})[0])[0, 0]
    low, high = float(result.min()), float(result.max())
    alpha = (result - low) / max(high - low, 1e-8)
    return Image.fromarray(np.rint(alpha * 255).clip(0, 255).astype('uint8')).resize(image.size, Image.Resampling.LANCZOS)


def segment_data_url(data):
    path = model_path()
    if not path.is_file():
        raise FileNotFoundError('Local foreground model is not installed')
    raw = data.split(',', 1)[-1]
    content = base64.b64decode(raw, validate=True)
    with Image.open(io.BytesIO(content)) as source:
        if source.width * source.height > 32_000_000:
            raise ValueError('Image exceeds 32 megapixels')
        image = ImageOps.exif_transpose(source).convert('RGB')
    with _inference_lock:
        mask = predict_mask(image, _session(str(path)))
    output = io.BytesIO()
    mask.save(output, format='PNG')
    return {'mask': 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode('ascii'),
            'width': image.width, 'height': image.height, 'engine': 'isnet-general-use'}
