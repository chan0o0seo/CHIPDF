"""Manual OCR/brush persistence, pixel boundaries and failure behavior."""
from test_studio import APP, ROOT
from copy import deepcopy
import base64
import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image, ImageDraw
from studio.document_io import import_files, png_data, render_page, validate_bundle
from studio.model import BackgroundPatch, Page, Paragraph, Project, Run, TextBox
from studio.recognition import (PSM, encode_png, make_erase_patch, recognize_region,
                                restored_background, restore_mask, validate_patches)
from studio.storage import load_bundle, save_project


def png(image):
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def decoded(data):
    with Image.open(io.BytesIO(data)) as image:
        return image.convert("RGBA")


class FakeOCR:
    """Only OCR is replaced; selection, restoration and serialization stay real."""
    def __init__(self, text="日 本 語\n選 択", bounds=(4, 6, 44, 26), after_read=None):
        self.text, self.bounds, self.after_read = text, bounds, after_read
        self.options = None
        self.sample = None

    def __call__(self, **options):
        self.options = options
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def SetImage(self, sample):
        self.sample = sample.copy()

    def SetSourceResolution(self, dpi):
        self.dpi = dpi

    def Recognize(self):
        if self.after_read:
            self.after_read()

    def GetUTF8Text(self):
        return self.text

    def MeanTextConf(self):
        return 92

    def GetIterator(self):
        return self if self.bounds else None

    def BoundingBox(self, level):
        return self.bounds

    def Next(self, level):
        return False


class ManualRegionTests(unittest.TestCase):
    def source(self, alpha=255):
        image = Image.new("RGBA", (100, 80), (205, 225, 240, alpha))
        draw = ImageDraw.Draw(image)
        draw.rectangle((24, 24, 31, 35), fill=(0, 0, 0, alpha))
        draw.rectangle((70, 50, 75, 55), fill=(15, 30, 45, alpha))
        return image

    def recognize(self, image, bounds, fake=None, **kwargs):
        fake = fake or FakeOCR()
        with patch("studio.recognition.PyTessBaseAPI", fake), patch("studio.recognition.model_path", return_value=Path("test-models")):
            return recognize_region(png(image), bounds, **kwargs), fake

    def manual_box(self, region):
        x, y, width, height = region.rect
        return TextBox(x=x, y=y, width=max(24, width), height=max(24, height),
                       paragraphs=[Paragraph([Run("")])], source_text=region.text,
                       source_rect=region.rect, erase_rect=region.erase_rect,
                       erase_patch=region.patch, erase_mask=region.mask,
                       erase_when_empty=True)

    def test_rectangle_keeps_user_bounds_not_ocr_bounds(self):
        source = self.source(alpha=137)
        region, fake = self.recognize(source, [20.2, 20.4, 24.1, 24.1])
        self.assertEqual(region.rect, [20, 20, 25, 25])
        self.assertEqual(region.erase_rect, region.rect)
        self.assertEqual(region.text, "日本語選択")
        self.assertEqual(region.lines, [[22, 23, 42, 33]])
        self.assertEqual(region.line_height, 10)
        self.assertEqual(region.confidence, 92)
        self.assertEqual(fake.sample.size, (50, 50))
        self.assertEqual(fake.options["psm"], PSM.SINGLE_BLOCK)
        self.assertEqual(fake.options["lang"], "jpn")
        mask = Image.open(io.BytesIO(base64.b64decode(region.mask)))
        self.assertEqual(mask.getextrema(), (255, 255), "The full chosen rectangle is erased")
        result = decoded(restored_background(png(source), [self.manual_box(region)]))
        for y in range(source.height):
            for x in range(source.width):
                if not (20 <= x < 45 and 20 <= y < 45):
                    self.assertEqual(result.getpixel((x, y)), source.getpixel((x, y)))
        self.assertEqual(result.getchannel("A").tobytes(), source.getchannel("A").tobytes())
        self.assertGreater(result.getpixel((27, 29))[0], 190)

    def test_clipped_rectangle_uses_only_page_pixels(self):
        region, fake = self.recognize(self.source(), [-10.4, 60.2, 40, 50])
        self.assertEqual(region.rect, [0, 60, 30, 20])
        self.assertEqual(region.erase_rect, [0, 60, 30, 20])
        self.assertEqual(fake.sample.size, (60, 40))

    def test_vertical_ocr_uses_vertical_model_and_line_width(self):
        region, fake = self.recognize(self.source(), [20, 20, 25, 30], vertical=True)
        self.assertEqual(fake.options["psm"], PSM.SINGLE_BLOCK_VERT_TEXT)
        self.assertEqual(fake.options["lang"], "jpn_vert")
        self.assertEqual(region.line_height, 20)

    def test_blank_ocr_still_supports_empty_manual_box_erasure(self):
        source = self.source()
        region, _ = self.recognize(source, [20, 20, 25, 25], FakeOCR(text="", bounds=None))
        obj = self.manual_box(region)
        self.assertEqual((obj.source_text, obj.text, region.confidence), ("", "", 0))
        result = decoded(restored_background(png(source), [obj]))
        self.assertGreater(result.getpixel((27, 29))[0], 190)
        obj.x, obj.y, obj.rotation = 60, 0, 50
        self.assertEqual(decoded(restored_background(png(source), [obj])).tobytes(), result.tobytes())
        obj.erase_enabled = False
        self.assertEqual(decoded(restored_background(png(source), [obj])).tobytes(), source.tobytes())
        obj.erase_enabled, obj.erase_when_empty = True, False
        self.assertEqual(decoded(restored_background(png(source), [obj])).tobytes(), source.tobytes(),
                         "Legacy empty automatic-OCR boxes leave the original visible")

    def test_invalid_rectangle_fails_before_ocr(self):
        invalid = ([0, 0, 0, 5], [0, 0, -1, 5], [101, 0, 25, 25], [0, 81, 25, 25],
                   [0, 0, True, 5], [float("nan"), 0, 25, 25], [0, 0, float("inf"), 25], [1, 2, 3])
        with patch("studio.recognition.PyTessBaseAPI") as api:
            for bounds in invalid:
                with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                    recognize_region(png(self.source()), bounds)
            with self.assertRaises(ValueError):
                recognize_region(png(Image.new("RGBA", (1000, 1000))), [0, 0, 800, 800])
            api.assert_not_called()

    def test_cancel_before_and_after_ocr_does_not_prepare_a_patch(self):
        cancel = threading.Event()
        cancel.set()
        with patch("studio.recognition.PyTessBaseAPI") as api, self.assertRaises(InterruptedError):
            recognize_region(png(self.source()), [20, 20, 25, 25], cancel)
        api.assert_not_called()
        cancel.clear()
        fake = FakeOCR(after_read=cancel.set)
        with patch("studio.recognition._make_patch") as make_patch, self.assertRaises(InterruptedError):
            self.recognize(self.source(), [20, 20, 25, 25], fake, cancelled=cancel)
        make_patch.assert_not_called()

    def test_brush_restores_only_mask_and_preserves_source_alpha(self):
        source = self.source(alpha=137)
        original = png(source)
        mask = Image.new("L", source.size)
        ImageDraw.Draw(mask).ellipse((19, 19, 38, 40), fill=255)
        record = make_erase_patch(original, png(mask))
        self.assertEqual(record.rect, [19, 19, 20, 22])
        result = decoded(restored_background(original, [], [record]))
        self.assertGreater(result.getpixel((27, 29))[0], 190)
        self.assertEqual(result.getchannel("A").tobytes(), source.getchannel("A").tobytes())
        for before, after, selected in zip(source.getdata(), result.getdata(), mask.getdata()):
            if not selected:
                self.assertEqual(before, after)
        self.assertEqual(png(source), original, "Creating a repair never edits original image data")

    def test_rgba_mask_uses_alpha_and_blends_soft_edge_once(self):
        source = Image.new("RGBA", (20, 20), "white")
        source.putpixel((10, 10), (0, 0, 0, 255))
        mask = Image.new("RGBA", source.size, (255, 255, 255, 0))
        mask.putpixel((10, 10), (0, 0, 0, 128))
        record = make_erase_patch(png(source), png(mask))
        self.assertEqual(record.rect, [10, 10, 1, 1])
        result = decoded(restored_background(png(source), [], [record]))
        self.assertEqual(result.getpixel((10, 10)), (128, 128, 128, 255))
        self.assertEqual(result.getpixel((0, 0)), source.getpixel((0, 0)))

    def test_brush_rejects_empty_mismatched_and_unbounded_selections(self):
        source = self.source()
        for mask in (Image.new("L", source.size), Image.new("L", (1, 1), 255),
                     Image.new("L", source.size, 255)):
            with self.subTest(size=mask.size, range=mask.getextrema()), self.assertRaises(ValueError):
                make_erase_patch(png(source), png(mask))
        with self.assertRaises(ValueError):
            make_erase_patch(png(Image.new("RGBA", (1000, 1000), "white")),
                             png(Image.new("L", (1000, 1000), 255)))
        wide_source = Image.new("RGBA", (3000, 3000), "white")
        sparse = Image.new("L", wide_source.size)
        sparse.putpixel((0, 0), 255)
        sparse.putpixel((2999, 2999), 255)
        with self.assertRaises(ValueError):
            make_erase_patch(png(wide_source), png(sparse))

    def test_brush_cancel_during_restoration_preserves_inputs(self):
        source = self.source()
        mask = Image.new("L", source.size)
        ImageDraw.Draw(mask).rectangle((20, 20, 40, 40), fill=255)
        before_source, before_mask = source.tobytes(), mask.tobytes()
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            return calls >= 4
        with self.assertRaises(InterruptedError):
            restore_mask(source, mask, cancel)
        self.assertEqual(source.tobytes(), before_source)
        self.assertEqual(mask.tobytes(), before_mask)

    def test_later_brush_patch_overrides_overlapping_text_repair(self):
        source = Image.new("RGBA", (50, 50), "white")
        text = TextBox(paragraphs=[Paragraph([Run("")])], erase_when_empty=True,
                       erase_rect=[10, 10, 24, 24],
                       erase_patch=encode_png(Image.new("RGBA", (24, 24), "gray")),
                       erase_mask=encode_png(Image.new("L", (24, 24), 255)))
        brush = BackgroundPatch(rect=[15, 15, 5, 5],
                                patch=encode_png(Image.new("RGBA", (5, 5), "white")),
                                mask=encode_png(Image.new("L", (5, 5), 255)))
        result = decoded(restored_background(png(source), [text], [brush]))
        self.assertEqual(result.getpixel((16, 16)), (255, 255, 255, 255))
        self.assertEqual(result.getpixel((11, 11)), (128, 128, 128, 255))

    def test_corrupt_patch_data_is_rejected_even_without_text_objects(self):
        record = BackgroundPatch(rect=[20, 20, 2, 2],
                                 patch=encode_png(Image.new("RGBA", (2, 2), "white")),
                                 mask=encode_png(Image.new("L", (2, 2), 255)))
        page = Page(width=100, height=80, background_patches=[record])
        validate_patches(page)
        variants = [dict(patch="not-base64"), dict(mask=encode_png(Image.new("L", (2, 2)))),
                    dict(patch=encode_png(Image.new("RGB", (2, 2), "white"))),
                    dict(mask=encode_png(Image.new("L", (3, 2), 255))),
                    dict(rect=[99, 79, 2, 2]), dict(rect=[20.5, 20, 2, 2]), dict(id="invalid")]
        for changes in variants:
            damaged = deepcopy(page)
            for key, value in changes.items():
                setattr(damaged.background_patches[0], key, value)
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                validate_patches(damaged)
        duplicate = deepcopy(page)
        duplicate.background_patches.append(deepcopy(record))
        with self.assertRaises(ValueError):
            validate_patches(duplicate)

    def test_schema_rejects_bad_patch_structure_and_nonboolean_manual_flag(self):
        record = BackgroundPatch(rect=[20, 20, 2, 2],
                                 patch=encode_png(Image.new("RGBA", (2, 2), "white")),
                                 mask=encode_png(Image.new("L", (2, 2), 255)))
        project = Project(pages=[Page(width=100, height=80, objects=[TextBox()], background_patches=[record])])
        variants = [{"rect": [20, 20, True, 2]}, {"rect": [20, 20, 2.0, 2]}, {"extra": 1},
                    {"id": project.pages[0].objects[0].id}, {"mask": ""}]
        for changes in variants:
            data = project.to_dict()
            data["pages"][0]["background_patches"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                Project.from_dict(data)
        for flag in (0, 1, "false", None):
            data = project.to_dict()
            data["pages"][0]["objects"][0]["erase_when_empty"] = flag
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                Project.from_dict(data)

    def test_project_roundtrip_and_export_keep_repairs_and_original_asset(self):
        source = self.source()
        original = png(source)
        region, _ = self.recognize(source, [20, 20, 25, 25])
        mask = Image.new("L", source.size)
        ImageDraw.Draw(mask).rectangle((68, 48, 77, 57), fill=255)
        record = make_erase_patch(original, png(mask))
        page = Page(width=100, height=80, objects=[self.manual_box(region)], background_patches=[record])
        project = Project(pages=[page])
        expected = decoded(restored_background(original, page.objects, page.background_patches))
        with tempfile.TemporaryDirectory(dir=ROOT / "qa") as folder:
            path = Path(folder) / "범위와 브러시.twproj"
            save_project(path, project, original)
            reopened, assets, project_file = import_files([path])
            self.assertEqual(project_file, path.resolve())
            self.assertEqual(reopened, project)
            self.assertEqual(reopened.version, 8)
            self.assertEqual(assets[page.asset], original)
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.read(page.asset), original)
            result = decoded(png_data(render_page(reopened.pages[0], assets[page.asset])))
            self.assertEqual(result.tobytes(), expected.tobytes())
            self.assertGreater(result.getpixel((27, 29))[0], 190)
            self.assertGreater(result.getpixel((72, 52))[0], 190)

    def test_legacy_schema_defaults_preserve_empty_original_text(self):
        source = self.source()
        region, _ = self.recognize(source, [20, 20, 25, 25])
        project = Project(pages=[Page(width=100, height=80, objects=[self.manual_box(region)])])
        data = project.to_dict()
        data["version"] = 6
        data["pages"][0].pop("background_patches")
        data["pages"][0]["objects"][0].pop("erase_when_empty")
        migrated = Project.from_dict(data)
        self.assertEqual(migrated.version, 8)
        self.assertEqual(migrated.pages[0].background_patches, [])
        self.assertFalse(migrated.pages[0].objects[0].erase_when_empty)
        result = decoded(restored_background(png(source), migrated.pages[0].objects))
        self.assertEqual(result.tobytes(), source.tobytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
