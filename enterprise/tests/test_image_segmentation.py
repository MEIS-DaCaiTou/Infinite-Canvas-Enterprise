import base64
import io
import unittest
from unittest.mock import patch
from pathlib import Path

from PIL import Image
from enterprise.image_segmentation import predict_mask, segment_data_url


class FakeSession:
    def get_inputs(self):
        return [type('Input', (), {'name': 'image'})()]

    def run(self, _, inputs):
        import numpy as np
        assert inputs['image'].shape == (1, 3, 1024, 1024)
        return [np.array([[[[0., 1.], [0., 1.]]]], dtype=np.float32)]


class ImageSegmentationTests(unittest.TestCase):
    def test_mask_matches_original_size_and_soft_alpha(self):
        mask=predict_mask(Image.new('RGB', (320, 240), 'red'), FakeSession())
        self.assertEqual(mask.size, (320, 240))
        self.assertEqual(mask.getpixel((0, 120)), 0)
        self.assertEqual(mask.getpixel((319, 120)), 255)

    def test_codec_returns_mask_only_without_asset_write(self):
        source=io.BytesIO();Image.new('RGB', (160, 120), 'red').save(source, 'PNG')
        with patch('enterprise.image_segmentation.model_path', return_value=Path(__file__)), patch('enterprise.image_segmentation._session', return_value=FakeSession()):
            result=segment_data_url('data:image/png;base64,'+base64.b64encode(source.getvalue()).decode())
        mask=Image.open(io.BytesIO(base64.b64decode(result['mask'].split(',')[1])))
        self.assertEqual(mask.mode, 'L');self.assertEqual(mask.size, (160, 120))
        self.assertNotIn('url', result)

    def test_missing_model_is_explicit(self):
        with patch('enterprise.image_segmentation.model_path', return_value=Path('missing-local-model.onnx')):
            with self.assertRaises(FileNotFoundError):segment_data_url('invalid')


if __name__=='__main__':unittest.main()
