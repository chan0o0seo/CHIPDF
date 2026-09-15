"""Native text clips preserve exact background pixels, not interpolated color."""
from test_studio import APP
from contextlib import closing
from io import BytesIO
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
import pypdfium2 as pdfium
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader
from studio.pdf_text_stream import TextlessPdf
from studio.recognition import (native_background_patch, make_erase_patch, prepare_patch,
                                recognize, restored_background)
from studio.model import TextBox, Paragraph, Run
from test_manual_regions import png


def clipped_pdf(text=True, mode=7, nested=False):
    out = BytesIO()
    c = Canvas(out, pagesize=(240, 180), pageCompression=1)
    texture = Image.new('RGB', (240, 180))
    for y in range(180):
        for x in range(240):
            texture.putpixel((x, y), (120+x//3, 60+y//2, 140+(x+y)%71))
    c.drawImage(ImageReader(texture), 0, 0, 240, 180)
    c.setStrokeColorRGB(0, 1, 1)
    c.line(0, 60, 240, 60)
    if nested:
        c.beginForm('text-form', 0, 0, 240, 180)
    # Background drawing in the same graphics group must survive too.
    c.saveState()
    c.setFillColorRGB(.1, .8, .3)
    c.rect(10, 100, 200, 40, fill=1, stroke=0)
    if text:
        t = c.beginText(25, 110)
        t.setFont('Helvetica', 22)
        t.setTextRenderMode(mode)
        t.textOut('NATIVE TEXT')
        c.drawText(t)
        c.saveState()
        c.setFillColorRGB(.9, .1, .05)
        c.rect(0, 0, 240, 180, fill=1, stroke=0)
        c.restoreState()
    c.restoreState()
    if nested:
        c.endForm()
        c.doForm('text-form')
    # A vector line after restoring the text clip must remain.
    c.setStrokeColorRGB(.9, .9, .1)
    c.line(0, 120, 240, 120)
    c.save()
    return out.getvalue()


def render(data, scale=2):
    with pdfium.PdfDocument(data) as doc, closing(doc[0]) as page, closing(page.render(scale=scale)) as bitmap:
        return bitmap.to_pil().convert('RGBA').copy()


class PdfTextStreamTests(unittest.TestCase):
    def test_auto_ocr_oversized_paragraph_retains_fallback_patch(self):
        clean = Image.new('RGBA', (820, 820), 'white')
        original = clean.copy()
        ImageDraw.Draw(original).rectangle((30, 30, 45, 45), fill='black')
        with patch('studio.recognition.PyTessBaseAPI') as factory, \
                patch('studio.recognition.model_path', return_value=Path('test-models')), \
                patch('studio.recognition.prepare_patch', wraps=prepare_patch) as fallback:
            iterator = factory.return_value.__enter__.return_value.GetIterator.return_value
            iterator.GetUTF8Text.return_value = '日本語'
            # OCR runs at twice the source size. A mostly empty paragraph can
            # exceed the native selection limit while its actual ink is small.
            iterator.BoundingBox.return_value = (20, 20, 1620, 1620)
            iterator.Confidence.return_value = 92
            iterator.Next.return_value = False
            regions = recognize(png(original), threading.Event(), lambda message: None,
                                clean_background=png(clean))
        self.assertEqual(len(regions), 1)
        region = regions[0]
        self.assertEqual(region.rect, [10, 10, 800, 800])
        fallback.assert_called_once()
        self.assertEqual(region.text, '日本語')
        self.assertTrue(region.patch)
        self.assertTrue(region.mask)
        obj = TextBox(paragraphs=[Paragraph([Run('번역')])],
                      erase_patch=region.patch, erase_mask=region.mask,
                      erase_rect=region.erase_rect)
        restored = Image.open(BytesIO(restored_background(png(original), [obj]))).convert('RGBA')
        self.assertEqual(restored.tobytes(), clean.tobytes())

    def test_clipped_paint_preserves_pattern_and_same_group_background(self):
        for mode in (4, 5, 6, 7):
            for nested in (False, True):
                with self.subTest(mode=mode, nested=nested):
                    source = clipped_pdf(mode=mode, nested=nested)
                    clean, count = TextlessPdf(BytesIO(source)).render(0, 2)
                    expected = render(clipped_pdf(False, nested=nested))
                    self.assertGreater(count, 0)
                    self.assertEqual(Image.open(BytesIO(clean)).convert('RGBA').tobytes(), expected.tobytes())
                    self.assertNotEqual(render(source).tobytes(), expected.tobytes())

    def test_rectangle_and_brush_use_exact_underlying_pixels_without_inpainting(self):
        original = render(clipped_pdf())
        clean = render(clipped_pdf(False))
        selection = Image.new('L', original.size)
        ImageDraw.Draw(selection).rectangle((35, 70, 400, 180), fill=255)
        with patch('studio.recognition.restore_mask', side_effect=AssertionError('No inpainting for native text')):
            patch_png, mask, rect = native_background_patch(png(original), png(clean), selection)
            obj = TextBox(paragraphs=[Paragraph([Run('')])], erase_when_empty=True,
                          erase_patch=patch_png, erase_mask=mask, erase_rect=rect)
            result = Image.open(BytesIO(restored_background(png(original), [obj]))).convert('RGBA')
            expected = original.copy()
            expected.paste(clean, (0, 0), selection)
            self.assertEqual(result.tobytes(), expected.tobytes())
            brush = make_erase_patch(png(original), png(selection), clean_background=png(clean))
            self.assertEqual(Image.open(BytesIO(restored_background(png(original), [], [brush]))).convert('RGBA').tobytes(), expected.tobytes())

    def test_stream_source_is_not_mutated_or_written(self):
        data = clipped_pdf(nested=True)
        helper = TextlessPdf(BytesIO(data))
        before = helper.reader.pages[0].get_contents().get_data()
        first = helper.render(0, 2)[0]
        self.assertEqual(first, helper.render(0, 2)[0])
        self.assertEqual(helper.reader.pages[0].get_contents().get_data(), before)

    def test_cancel_and_unsupported_stream_do_not_publish_background(self):
        helper = TextlessPdf(BytesIO(clipped_pdf()))
        with self.assertRaises(InterruptedError):
            helper.render(0, 2, cancelled=lambda: True)
        with patch('studio.pdf_text_stream.MAX_OPS', 1):
            self.assertIsNone(helper.render(0, 2))


if __name__ == '__main__':
    unittest.main()
