"""Japanese text on transparent images: recognition and removal keep the transparency."""
import io
from pathlib import Path
import sys
from threading import Event
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / '.deps'), str(ROOT)]

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from studio.recognition import recognize, restore_mask


def card():
    image = Image.new('RGBA', (640, 360), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((40, 60, 600, 300), 30, fill=(30, 60, 120, 230))
    font = ImageFont.truetype('C:/Windows/Fonts/msgothic.ttc', 56)
    draw.text((90, 140), 'ゲーム開始', font=font, fill='white')
    return image


@unittest.skipUnless(Path('C:/Windows/Fonts/msgothic.ttc').exists(), 'needs MS Gothic')
class TransparentImageTests(unittest.TestCase):
    def test_text_over_transparent_pixels_is_recognized(self):
        stream = io.BytesIO()
        card().save(stream, 'PNG')
        regions = recognize(stream.getvalue(), Event(), lambda message: None)
        self.assertEqual(len(regions), 1)
        self.assertIn('開始', regions[0].text)

    def test_removed_letters_take_the_card_alpha(self):
        source = card()
        ink = Image.fromarray(((np.asarray(source)[..., 0] > 100)*255).astype(np.uint8))
        mask = ink.filter(ImageFilter.MaxFilter(5))
        letters = np.asarray(mask) > 0
        restored = np.asarray(restore_mask(source, mask)).astype(int)
        # No opaque trace of the letters remains on the translucent card.
        self.assertTrue((abs(restored[letters] - (30, 60, 120, 230)) <= 3).all())
        outside = np.asarray(source)[..., 3] == 0
        self.assertEqual(int(restored[outside][..., 3].max()), 0)


if __name__ == '__main__':
    unittest.main()
