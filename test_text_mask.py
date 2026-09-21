"""Focused colour-mask invariants; no Qt or model download required."""
import unittest

from PIL import Image, ImageDraw

from studio.text_mask import make_text_mask


class TextMaskTests(unittest.TestCase):
    def test_legacy_colour_distance_and_binary_output(self):
        source = Image.new("RGB", (4, 1))
        source.putdata([(20, 30, 40), (23, 34, 40), (24, 34, 40), (0, 0, 0)])
        selection = Image.new("L", source.size, 1)
        result = make_text_mask(source, selection, "#141e28", tolerance=5, expansion=0)
        self.assertEqual(result.mode, "L")
        self.assertEqual(result.tobytes(), bytes([255, 255, 0, 0]))
        self.assertEqual(result.tobytes(), make_text_mask(
            source, selection, (20, 30, 40), tolerance=5, expansion=0).tobytes())

    def test_expansion_manual_and_protection_never_leave_allowed_pixels(self):
        source = Image.new("RGBA", (9, 9), (255, 255, 255, 255))
        source.putpixel((2, 2), (0, 0, 0, 255))
        source.putpixel((3, 2), (0, 0, 0, 0))
        selection = Image.new("L", source.size)
        ImageDraw.Draw(selection).rectangle((2, 2, 6, 6), fill=255)
        selection.putpixel((3, 3), 0)
        manual = Image.new("L", source.size)
        for point in ((0, 0), (5, 5), (6, 6)):
            manual.putpixel(point, 255)
        protected = Image.new("L", source.size)
        for point in ((2, 3), (6, 6)):
            protected.putpixel(point, 1)
        originals = [image.tobytes() for image in (source, selection, manual, protected)]
        result = make_text_mask(source, selection, (0, 0, 0), 0, 1,
                                protected=protected, manual=manual)
        self.assertEqual({(x, y) for y in range(9) for x in range(9)
                          if result.getpixel((x, y))}, {(2, 2), (5, 5)})
        self.assertEqual(originals,
                         [image.tobytes() for image in (source, selection, manual, protected)])

    def test_empty_selection_still_validates_inputs(self):
        source = Image.new("RGB", (3, 3))
        selection = Image.new("L", source.size)
        self.assertIsNone(make_text_mask(source, selection, "#000000").getbbox())
        for invalid in ({"tolerance": float("nan")}, {"expansion": -1},
                        {"expansion": 1.5}, {"protected": Image.new("L", (1, 1))}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                make_text_mask(source, selection, "#000000", **invalid)
        with self.assertRaises(ValueError):
            make_text_mask(source, selection, "black")


if __name__ == "__main__":
    unittest.main()
