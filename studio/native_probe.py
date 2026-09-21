"""Explicit packaged-build verification; never runs during normal editing."""
import json
import platform
import sys


def verify_native_runtime(output):
    from PIL import Image, ImageDraw
    from tesserocr import PyTessBaseAPI, PSM
    from .recognition import model_path
    from .inpaint_engine import restore_lama

    sample = Image.new('RGB', (96, 64), (80, 140, 200))
    loaded = []
    for language in ('jpn', 'jpn_vert'):
        with PyTessBaseAPI(path=str(model_path()), lang=language, psm=PSM.SINGLE_BLOCK) as api:
            api.SetImage(sample)
            api.Recognize()
            api.GetUTF8Text()
            loaded.append(api.GetInitLanguagesAsString())
    mask = Image.new('L', sample.size)
    ImageDraw.Draw(mask).rectangle((40, 24, 55, 39), fill=255)
    restored = restore_lama(sample, mask)
    assert restored.size == sample.size
    before, after = sample.convert('RGBA'), restored.convert('RGBA')
    for y in range(sample.height):
        for x in range(sample.width):
            if not mask.getpixel((x, y)):
                assert before.getpixel((x, y)) == after.getpixel((x, y)), 'Unselected pixels changed'
    report = {'platform': sys.platform, 'architecture': platform.machine(),
              'ocr_languages': loaded, 'lama_inference': True,
              'unselected_pixels_preserved': True}
    (output / 'native-smoke.json').write_text(json.dumps(report, indent=2), 'utf-8')
