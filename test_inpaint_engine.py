"""Small contract checks with a fake session, not a LaMa quality benchmark."""
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from studio import inpaint_engine as engine


class InpaintEngineTests(unittest.TestCase):
    def test_tiles_use_original_preserve_alpha_and_unmasked_pixels(self):
        source = np.zeros((630, 850, 4), dtype=np.uint8)
        source[:, :, 0] = np.arange(850, dtype=np.uint16)[None, :] % 251
        source[:, :, 1] = np.arange(630, dtype=np.uint16)[:, None] % 239
        source[:, :, 2] = 37
        source[:, :, 3] = np.arange(850, dtype=np.uint16)[None, :] % 255
        original = Image.fromarray(source)
        mask = Image.new("L", original.size)
        ImageDraw.Draw(mask).rectangle((175, 145, 735, 530), fill=255)
        calls = []

        class Session:
            def run(self, names, feeds):
                image, selected = feeds["image"], feeds["mask"]
                self_test.assertEqual(image.shape, (1, 3, 512, 512))
                self_test.assertEqual(selected.shape, (1, 1, 512, 512))
                self_test.assertEqual(image.dtype, np.float32)
                self_test.assertEqual(selected.dtype, np.float32)
                self_test.assertTrue(np.isin(selected, (0.0, 1.0)).all())
                # Every input keeps the original blue channel, including overlap.
                self_test.assertTrue(np.allclose(image[0, 2], 37 / 255))
                calls.append(1)
                return [np.full((1, 3, 512, 512), 123.0, dtype=np.float32)]

        self_test = self
        with patch.object(engine, "_get_session", return_value=Session()):
            restored = np.asarray(engine.restore_lama(original, mask))
        chosen = np.asarray(mask) != 0
        self.assertGreater(len(calls), 1)
        np.testing.assert_array_equal(restored[~chosen], source[~chosen])
        np.testing.assert_array_equal(restored[:, :, 3], source[:, :, 3])
        self.assertTrue((restored[chosen, :3] == 123).all())
        np.testing.assert_array_equal(np.asarray(original), source)

    def test_tiny_image_padding_noop_and_cancellation(self):
        source = Image.new("RGBA", (19, 7), (20, 40, 60, 80))
        empty = Image.new("L", source.size)
        with patch.object(engine, "_get_session") as loader:
            self.assertEqual(engine.restore_lama(source, empty).tobytes(), source.tobytes())
            loader.assert_not_called()
        white = Image.new("L", source.size, 255)

        class Session:
            def run(self, names, feeds):
                return [feeds["image"] * 255]

        with patch.object(engine, "_get_session", return_value=Session()):
            result = engine.restore_lama(source, white)
            self.assertEqual(result.size, source.size)
            self.assertEqual(result.tobytes(), source.tobytes())
            with self.assertRaises(InterruptedError):
                engine.restore_lama(source, white, cancelled=lambda: True)


if __name__ == "__main__":
    unittest.main()
