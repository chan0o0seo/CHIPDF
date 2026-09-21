"""Legacy text-colour selection shared by the local restoration engines.

White pixels mean removal. Only the selection bounding box is inspected, and
the resulting binary mask never includes protected or fully transparent pixels.
"""
from __future__ import annotations

import math
from numbers import Integral, Real
import re

import numpy as np
from PIL import Image, ImageFilter


def _mask_image(value: Image.Image, size: tuple[int, int], name: str) -> None:
    if not isinstance(value, Image.Image) or value.size != size:
        raise ValueError(f"{name} 마스크 크기가 원본 이미지와 같아야 합니다.")


def _rgb_color(color: tuple[int, int, int] | str) -> tuple[int, int, int]:
    if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))
    if (isinstance(color, tuple) and len(color) == 3
            and all(isinstance(channel, Integral) and not isinstance(channel, bool)
                    and 0 <= channel <= 255 for channel in color)):
        return tuple(int(channel) for channel in color)
    raise ValueError("글자색은 #RRGGBB 또는 0~255의 RGB 튜플이어야 합니다.")


def make_text_mask(
    source: Image.Image,
    selection: Image.Image,
    color: tuple[int, int, int] | str,
    tolerance: float = 65,
    expansion: int = 1,
    protected: Image.Image | None = None,
    manual: Image.Image | None = None,
) -> Image.Image:
    """Select text by the previous editor's Euclidean RGB colour distance.

    ``tolerance`` is in the legacy range 0..200. ``expansion`` adds 0..5 pixels
    around colour matches, then clips to the brush selection. Nonzero mask
    values are selected; manual additions are also clipped to the selection,
    and protection wins over additions. Source and input masks stay unchanged.
    An empty selection or no colour matches returns an empty L-mode mask.
    """
    if not isinstance(source, Image.Image) or min(source.size) <= 0:
        raise ValueError("원본 이미지가 올바르지 않습니다.")
    _mask_image(selection, source.size, "선택")
    for value, name in ((protected, "보호"), (manual, "수동 추가")):
        if value is not None:
            _mask_image(value, source.size, name)
    rgb_color = _rgb_color(color)
    if (not isinstance(tolerance, Real) or isinstance(tolerance, bool)
            or not math.isfinite(tolerance) or not 0 <= tolerance <= 200):
        raise ValueError("글자색 허용 오차는 0~200이어야 합니다.")
    if (not isinstance(expansion, Integral) or isinstance(expansion, bool)
            or not 0 <= expansion <= 5):
        raise ValueError("글자 마스크 확장은 0~5의 정수여야 합니다.")

    selection = selection.convert("L")
    result = Image.new("L", source.size, 0)
    bounds = selection.getbbox()
    if bounds is None:
        return result

    # Convert only the selected crop, including palette transparency if present.
    rgba = np.asarray(source.crop(bounds).convert("RGBA"))
    selected = np.asarray(selection.crop(bounds)) > 0
    visible = rgba[:, :, 3] > 0
    difference = rgba[:, :, :3].astype(np.int32) - np.asarray(rgb_color, dtype=np.int32)
    matches = ((difference * difference).sum(axis=2) <= float(tolerance) ** 2)
    matches &= selected & visible
    local_mask = Image.fromarray(matches.astype(np.uint8) * 255)
    if expansion:
        local_mask = local_mask.filter(ImageFilter.MaxFilter(2 * int(expansion) + 1))
    accepted = np.asarray(local_mask) > 0
    if manual is not None:
        accepted |= np.asarray(manual.crop(bounds).convert("L")) > 0
    accepted &= selected & visible
    if protected is not None:
        accepted &= np.asarray(protected.crop(bounds).convert("L")) == 0
    result.paste(Image.fromarray(accepted.astype(np.uint8) * 255), bounds[:2])
    return result
