"""Local OCR and bounded background restoration. No legacy-app runtime imports."""
from __future__ import annotations

import base64
from collections import deque
from dataclasses import dataclass, field
import hashlib
import io
import math
from pathlib import Path
import re
import sys
import tempfile

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
from .model import BackgroundPatch, TextBox
# This Windows wheel initializes cysignals at import time; import on the UI
# thread before running any Tesseract work in the background pool.
from tesserocr import PyTessBaseAPI, PSM, RIL


@dataclass
class Region:
    text: str
    rect: list[float]
    confidence: float
    line_height: float
    glyphs: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    patch: str = ""
    mask: str = ""
    erase_rect: list[float] | None = None
    source_method: str = "ocr"


def encode_png(image):
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


def model_path():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    source = root / "ocr-models" if getattr(sys, "frozen", False) else root / "vendor" / "tessdata"
    contents = {name: (source / name).read_bytes() for name in ("jpn.traineddata", "jpn_vert.traineddata")}
    if str(source).isascii():
        return source
    digest = hashlib.sha256(b"".join(contents.values())).hexdigest()[:16]
    cache = Path(tempfile.gettempdir()) / "TranslationStudio-ocr" / digest
    cache.mkdir(parents=True, exist_ok=True)
    for name, data in contents.items():
        target = cache / name
        if not target.exists() or hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(data).digest():
            from .storage import atomic_write
            atomic_write(target, data)
    if not str(cache).isascii():
        import ctypes
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(str(cache), buffer, len(buffer)) and buffer.value.isascii():
            return Path(buffer.value)
        raise ValueError("OCR 임시 경로를 준비하지 못했습니다. 영문 Windows 임시 폴더가 필요합니다.")
    return cache


def japanese_text(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # OCR spaces between Japanese characters are usually segmentation artifacts.
    text = "".join(lines)
    return re.sub(r"(?<=[\u3000-\u9fff]) +(?=[\u3000-\u9fff])", "", text)


def recognize(original: bytes, cancelled, progress, vertical=False, clean_background=None):
    source = Image.open(io.BytesIO(original)).convert("RGBA")
    ratio = min(2.0, 2400 / max(source.size))
    ratio = max(.3, ratio)
    sample = source.convert("RGB").resize((round(source.width * ratio), round(source.height * ratio)), Image.Resampling.LANCZOS)
    progress("카드의 글자를 읽고 있습니다…")
    groups = {}
    with PyTessBaseAPI(path=str(model_path()), lang="jpn_vert" if vertical else "jpn",
                      psm=PSM.SINGLE_BLOCK_VERT_TEXT if vertical else PSM.AUTO) as api:
        api.SetImage(ImageOps.autocontrast(sample.convert("L"), cutoff=1))
        api.SetSourceResolution(200)
        api.Recognize()
        iterator = api.GetIterator()
        if iterator is None:
            return []
        while True:
            if cancelled.is_set():
                return []
            text = japanese_text(iterator.GetUTF8Text(RIL.TEXTLINE) or "")
            box = iterator.BoundingBox(RIL.TEXTLINE)
            para = iterator.BoundingBox(RIL.PARA)
            if text and box and para:
                group = groups.setdefault(tuple(para), {"lines": [], "glyphs": []})
                group["lines"].append((text, box, iterator.Confidence(RIL.TEXTLINE)))
            if not iterator.Next(RIL.TEXTLINE):
                break
        iterator = api.GetIterator()
        while iterator:
            para = iterator.BoundingBox(RIL.PARA)
            box = iterator.BoundingBox(RIL.SYMBOL)
            if para and box and tuple(para) in groups:
                groups[tuple(para)]["glyphs"].append([v / ratio for v in box])
            if not iterator.Next(RIL.SYMBOL):
                break
    regions = []
    for group in groups.values():
        if cancelled.is_set():
            return []
        text = "".join(line[0] for line in group["lines"])
        if len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", text)) < 2:
            continue
        boxes = [line[1] for line in group["lines"]]
        x0, y0 = max(0, min(b[0] for b in boxes) / ratio), max(0, min(b[1] for b in boxes) / ratio)
        x1, y1 = min(source.width, max(b[2] for b in boxes) / ratio), min(source.height, max(b[3] for b in boxes) / ratio)
        if (x1 - x0) < 8 or (y1 - y0) < 8:
            continue
        confidence = sum(line[2] for line in group["lines"]) / len(group["lines"])
        line_height = sum((b[2]-b[0] if vertical else b[3]-b[1]) / ratio for b in boxes) / len(boxes)
        region = Region(text, [x0, y0, x1-x0, y1-y0], confidence, line_height, group["glyphs"])
        region.lines = [[v / ratio for v in box] for box in boxes]
        progress(f"원문 {len(regions) + 1}개 · 글자 배경 준비 중…")
        try:
            native = None
            if clean_background:
                try:
                    x, y, w, h = _selected_rect(region.rect, source.size)
                    selection = Image.new('L', source.size)
                    selection.paste(255, (x, y, x+w, y+h))
                    native = native_background_patch(original, clean_background, selection, cancelled)
                except ValueError:
                    # Sparse glyph masks may still fit when the full paragraph does not.
                    pass
            region.patch, region.mask, region.erase_rect = native or prepare_patch(source, region)
        except ValueError:
            # Recognition remains usable when a background cannot be reconstructed.
            pass
        regions.append(region)
    return sorted(regions, key=lambda r: (r.rect[1], r.rect[0]))


def _check_cancel(cancelled):
    if cancelled and (cancelled.is_set() if hasattr(cancelled, "is_set") else cancelled()):
        raise InterruptedError("중단됨 · 기존 작업은 유지됩니다.")


def _source_image(original):
    with Image.open(io.BytesIO(original)) as image:
        if max(image.size) > 16000 or image.width * image.height > 80_000_000:
            raise ValueError("이미지가 너무 큽니다.")
        return image.convert("RGBA")


def _selected_rect(rect, size):
    if (not isinstance(rect, (list, tuple)) or len(rect) != 4 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in rect) or
            min(rect[2:]) <= 0):
        raise ValueError("선택한 문장 범위가 올바르지 않습니다.")
    x, y, width, height = rect
    x0, y0 = max(0, math.floor(x)), max(0, math.floor(y))
    x1, y1 = min(size[0], math.ceil(x+width)), min(size[1], math.ceil(y+height))
    if x1 <= x0 or y1 <= y0 or (x1-x0)*(y1-y0) > 600_000:
        raise ValueError("선택한 문장 범위가 없거나 너무 큽니다. 작은 범위로 나눠 선택해 주세요.")
    return [x0, y0, x1-x0, y1-y0]


def recognize_region(original: bytes, rect, cancelled=None, progress=None, vertical=False, clean_background=None):
    """Read exactly one user-selected block, keeping its removal and editing bounds."""
    progress = progress or (lambda message: None)
    _check_cancel(cancelled)
    source = _source_image(original)
    selected = _selected_rect(rect, source.size)
    x, y, width, height = selected
    crop = source.crop((x, y, x+width, y+height))
    ratio = min(2.0, 2400 / max(crop.size))
    white = Image.new("RGBA", crop.size, "white")
    white.alpha_composite(crop)
    sample = white.convert("L").resize((max(1, round(width*ratio)), max(1, round(height*ratio))), Image.Resampling.LANCZOS)
    progress("선택한 문장의 일본어를 읽고 있습니다…")
    _check_cancel(cancelled)
    lines = []
    with PyTessBaseAPI(path=str(model_path()), lang="jpn_vert" if vertical else "jpn",
                      psm=PSM.SINGLE_BLOCK_VERT_TEXT if vertical else PSM.SINGLE_BLOCK) as api:
        api.SetImage(ImageOps.autocontrast(sample, cutoff=1))
        api.SetSourceResolution(200)
        api.Recognize()
        _check_cancel(cancelled)
        text = japanese_text(api.GetUTF8Text() or "")
        confidence = max(0, min(100, float(api.MeanTextConf()))) if text else 0
        iterator = api.GetIterator()
        while iterator:
            _check_cancel(cancelled)
            bounds = iterator.BoundingBox(RIL.TEXTLINE)
            if bounds:
                gx0, gy0, gx1, gy1 = bounds
                lines.append([x+gx0/ratio, y+gy0/ratio, x+gx1/ratio, y+gy1/ratio])
            if not iterator.Next(RIL.TEXTLINE):
                break
    line_height = (sum((b[2]-b[0] if vertical else b[3]-b[1]) for b in lines) / len(lines)
                   if lines else min(24, width if vertical else height))
    region = Region(text, selected, confidence, line_height, lines=lines)
    progress("선택 범위의 배경을 복원하고 있습니다…")
    mask = Image.new("L", source.size)
    mask.paste(255, (x, y, x+width, y+height))
    native = native_background_patch(original, clean_background, mask, cancelled)
    region.patch, region.mask, region.erase_rect = native or _make_patch(source, mask, cancelled, progress)
    return region


def native_background_patch(original, clean_background, selection, cancelled=None):
    """Use the PDF's actual background pixels, changing only selected text pixels.

    The clean image was rendered with native PDF text hidden. Keeping its
    difference mask avoids repainting graphics or earlier brush edits under
    otherwise empty parts of a selection. No interpolation is performed here.
    """
    if not clean_background:
        return None
    _check_cancel(cancelled)
    source, clean = _source_image(original), _source_image(clean_background)
    if source.size != clean.size or source.size != selection.size:
        raise ValueError('PDF 배경과 원본의 크기가 일치하지 않습니다.')
    bounds = selection.getbbox()
    if not bounds or sum(selection.histogram()[1:]) > 600_000:
        raise ValueError('지울 범위가 없거나 너무 큽니다.')
    x0, y0, x1, y1 = bounds
    if (x1-x0)*(y1-y0) > 8_000_000:
        raise ValueError('지울 범위가 너무 넓게 떨어져 있습니다.')
    difference = ImageChops.difference(source.crop(bounds), clean.crop(bounds))
    channels = difference.split()
    changed = channels[0]
    for channel in channels[1:]:
        changed = ImageChops.lighter(changed, channel)
    native_mask = ImageChops.darker(changed.point(lambda value: 255 if value else 0), selection.crop(bounds))
    if not native_mask.getbbox():
        return None
    result = encode_png(clean.crop(bounds)), encode_png(native_mask), [x0, y0, x1-x0, y1-y0]
    if max(len(result[0]), len(result[1])) > 8_000_000:
        raise ValueError('PDF 배경 기록이 너무 큽니다. 작은 범위로 나누어 선택해 주세요.')
    _check_cancel(cancelled)
    return result


def _make_patch(source, mask, cancelled=None, progress=None):
    _check_cancel(cancelled)
    bounds = mask.getbbox()
    if not bounds or sum(mask.histogram()[1:]) > 600_000:
        raise ValueError("지울 범위가 없거나 너무 큽니다. 작은 범위로 나눠 선택해 주세요.")
    x0, y0, x1, y1 = bounds
    if (x1-x0)*(y1-y0) > 8_000_000:
        raise ValueError("지울 범위가 너무 넓게 떨어져 있습니다. 나눠서 지워 주세요.")
    # Restore all selected pixels first; retain the original soft mask for one
    # composite at preview/export time, so antialiased brush edges are not blended twice.
    binary = mask.point(lambda value: 255 if value else 0)
    restored = restore_mask(source, binary, cancelled, progress)
    _check_cancel(cancelled)
    patch_png, mask_png = encode_png(restored.crop(bounds)), encode_png(mask.crop(bounds))
    if max(len(patch_png), len(mask_png)) > 8_000_000:
        raise ValueError("배경 지우기 기록이 너무 큽니다. 작은 범위로 나눠 선택해 주세요.")
    _check_cancel(cancelled)
    return patch_png, mask_png, [x0, y0, x1-x0, y1-y0]


def make_erase_patch(original: bytes, mask_png: bytes, cancelled=None, progress=None,
                     clean_background=None, native_original=None):
    """Turn a page-sized brush mask into one bounded, persistent background repair."""
    _check_cancel(cancelled)
    source = _source_image(original)
    if not isinstance(mask_png, bytes) or len(mask_png) > 12_000_000:
        raise ValueError("브러시 선택 기록이 없거나 너무 큽니다.")
    with Image.open(io.BytesIO(mask_png)) as image:
        if image.format != "PNG" or image.size != source.size:
            raise ValueError("브러시 선택 범위와 원본 크기가 일치하지 않습니다.")
        mask = image.getchannel("A") if image.mode in ("RGBA", "LA") else image.convert("L")
    if progress:
        progress("브러시로 선택한 부분의 배경을 복원하고 있습니다…")
    native = native_background_patch(native_original or original, clean_background, mask, cancelled)
    patch, encoded_mask, rect = native or _make_patch(source, mask, cancelled, progress)
    return BackgroundPatch(rect=rect, patch=patch, mask=encoded_mask)


def restore_mask(source, mask, cancelled=None, progress=None):
    """Port of the old editor's masked neighbor interpolation, without UI/storage coupling."""
    _check_cancel(cancelled)
    source = source.convert("RGBA")
    mask = mask.convert("L")
    if mask.size != source.size:
        raise ValueError("복원 범위와 원본 크기가 일치하지 않습니다.")
    bounds = mask.getbbox()
    if not bounds or sum(mask.histogram()[1:]) > 600_000:
        raise ValueError("복원할 글자 영역이 없거나 너무 큽니다.")
    x0, y0, x1, y1 = bounds
    box = (max(0, x0-4), max(0, y0-4), min(source.width, x1+4), min(source.height, y1+4))
    crop = source.convert("RGB").crop(box)
    local_mask = mask.crop(box)
    width, height = crop.size
    pending = bytearray(1 if value else 0 for value in local_mask.tobytes())
    pixels = crop.load()
    frontier = deque()
    directions = ((-1, 0), (1, 0), (0, -1), (0, 1))
    for y in range(height):
        if y % 16 == 0:
            _check_cancel(cancelled)
        for x in range(width):
            if pending[y*width+x] and any(0 <= x+dx < width and 0 <= y+dy < height and pending[(y+dy)*width+x+dx] == 0 for dx, dy in directions):
                frontier.append((x, y))
                pending[y*width+x] = 2
    while frontier:
        _check_cancel(cancelled)
        layer = []
        for index in range(len(frontier)):
            if index % 1024 == 0:
                _check_cancel(cancelled)
            x, y = frontier.popleft()
            neighbors = [pixels[x+dx, y+dy] for dx, dy in directions if 0 <= x+dx < width and 0 <= y+dy < height and pending[(y+dy)*width+x+dx] == 0]
            if neighbors:
                layer.append((x, y, tuple(round(sum(p[c] for p in neighbors) / len(neighbors)) for c in range(3))))
        for x, y, color in layer:
            pixels[x, y] = color
            pending[y*width+x] = 0
        for x, y, _ in layer:
            for dx, dy in directions:
                nx, ny = x+dx, y+dy
                if 0 <= nx < width and 0 <= ny < height and pending[ny*width+nx] == 1:
                    pending[ny*width+nx] = 2
                    frontier.append((nx, ny))
    if any(pending):
        raise ValueError("복원할 주변 배경이 부족합니다.")
    for _ in range(16):
        _check_cancel(cancelled)
        crop.paste(crop.filter(ImageFilter.GaussianBlur(.85)), (0, 0), local_mask)
    result = source.convert("RGBA")
    restored = crop.convert("RGBA")
    restored.putalpha(source.getchannel("A").crop(box))
    result.paste(restored, box[:2], local_mask)
    return result


def prepare_patch(source, region):
    x, y, w, h = region.rect
    box = (max(0, int(x)-3), max(0, int(y)-3), min(source.width, int(x+w)+4), min(source.height, int(y+h)+4))
    crop = source.crop(box)
    gray = crop.convert("L")
    hist = gray.histogram()
    total, median = 0, 127
    for value, count in enumerate(hist):
        total += count
        if total >= crop.width * crop.height / 2:
            median = value
            break
    mask = gray.point(lambda value: 255 if (value < median-35 if median >= 128 else value > median+35) else 0)
    selection = Image.new("L", crop.size)
    draw = ImageDraw.Draw(selection)
    # Individual symbol bounds omit characters Tesseract failed to recognize.
    # Select complete text lines so those strokes are removed as well.
    for gx0, gy0, gx1, gy1 in region.lines or region.glyphs:
        draw.rectangle((max(0, gx0-box[0]-2), max(0, gy0-box[1]-2), min(crop.width-1, gx1-box[0]+2), min(crop.height-1, gy1-box[1]+2)), fill=255)
    # Keep long, thin rules even when OCR includes an underline in a line box.
    rules = Image.new("L", crop.size)
    rule_draw = ImageDraw.Draw(rules)
    ink = mask.load()
    minimum_rule = max(70, int(region.line_height * 5))
    for row in range(crop.height):
        start = None
        for col in range(crop.width + 1):
            active = col < crop.width and ink[col, row] > 0
            if active and start is None:
                start = col
            elif not active and start is not None:
                if col - start >= minimum_rule:
                    rule_draw.line((start, row, col-1, row), fill=255)
                start = None
    selection = ImageChops.subtract(selection, rules)
    mask = ImageChops.darker(mask.filter(ImageFilter.MaxFilter(5)), selection)
    mask = ImageChops.darker(mask, crop.getchannel("A").point(lambda value: 255 if value else 0))
    # Rules stay in the final image, but must not be sampled as background color
    # while reconstructing adjacent letters (which otherwise leaves dark smears).
    donor_mask = ImageChops.lighter(mask, rules.filter(ImageFilter.MaxFilter(3)))
    restored = restore_mask(crop, donor_mask)
    return encode_png(restored), encode_png(mask), [box[0], box[1], crop.width, crop.height]


def _patch_images(rect, patch, mask, width, height, background=False):
    if (not isinstance(rect, (list, tuple)) or len(rect) != 4 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or int(v) != v for v in rect)):
        raise ValueError("invalid patch bounds")
    x, y, w, h = map(int, rect)
    if min(x, y) < 0 or min(w, h) < 1 or x+w > width or y+h > height or (background and w*h > 8_000_000):
        raise ValueError("invalid patch bounds")
    decoded = []
    for index, encoded in enumerate((patch, mask)):
        if not isinstance(encoded, str) or not encoded or len(encoded) > 8_000_000:
            raise ValueError("invalid patch payload")
        payload = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(payload)) as image:
            if image.format != "PNG" or image.size != (w, h) or (background and image.mode != ("RGBA" if index == 0 else "L")):
                raise ValueError("invalid patch image")
            image.verify()
        with Image.open(io.BytesIO(payload)) as image:
            decoded.append(image.convert("RGBA" if index == 0 else "L"))
    if background and (not decoded[1].getbbox() or sum(decoded[1].histogram()[1:]) > 600_000):
        raise ValueError("invalid patch selection")
    return decoded


def restored_background(original, objects, background_patches=()):
    result = Image.open(io.BytesIO(original)).convert("RGBA")
    for obj in objects:
        if isinstance(obj, TextBox) and (obj.text.strip() or obj.erase_when_empty) and obj.erase_enabled and obj.erase_patch and obj.erase_mask and obj.erase_rect:
            patch, mask = _patch_images(obj.erase_rect, obj.erase_patch, obj.erase_mask, result.width, result.height)
            result.paste(patch, tuple(int(v) for v in obj.erase_rect[:2]), mask)
    # Brush repairs are made from the visible background and must keep their
    # result even where an earlier text removal patch occupies the same pixels.
    for record in background_patches:
        patch, mask = _patch_images(record.rect, record.patch, record.mask, result.width, result.height, background=True)
        result.paste(patch, tuple(record.rect[:2]), mask)
    stream = io.BytesIO()
    result.save(stream, "PNG")
    return stream.getvalue()


def validate_patches(page):
    """Reject damaged restoration data before an imported project replaces edits."""
    identities = {obj.id for obj in page.objects}
    if not isinstance(page.background_patches, list) or len(page.background_patches) > 2000:
        raise ValueError("배경 지우기 기록이 올바르지 않습니다.")
    for record in page.background_patches:
        try:
            if not isinstance(record, BackgroundPatch) or not isinstance(record.id, str) or not re.fullmatch(r"[a-f0-9]{32}", record.id) or record.id in identities:
                raise ValueError("invalid patch identity")
            identities.add(record.id)
            _patch_images(record.rect, record.patch, record.mask, page.width, page.height, background=True)
        except (ValueError, TypeError, OSError, SyntaxError) as exc:
            raise ValueError("배경 지우기 기록이 손상되었습니다.") from exc
    for obj in page.objects:
        if not isinstance(obj, TextBox):
            continue
        if not obj.erase_patch and not obj.erase_mask:
            continue
        try:
            if not obj.erase_rect or not obj.erase_patch or not obj.erase_mask:
                raise ValueError("incomplete patch")
            _patch_images(obj.erase_rect, obj.erase_patch, obj.erase_mask, page.width, page.height)
        except (ValueError, TypeError, OSError, SyntaxError) as exc:
            raise ValueError("원문 제거 기록이 손상되었습니다.") from exc
