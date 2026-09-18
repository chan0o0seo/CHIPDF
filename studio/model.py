"""Versioned document data. No Qt objects or widget HTML in saved projects."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import re
from uuid import uuid4


def uid() -> str:
    return uuid4().hex


@dataclass
class Style:
    family: str = "맑은 고딕"
    size: float = 20.0
    color: str = "#253345"
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False


@dataclass
class Run:
    text: str = ""
    style: Style = field(default_factory=Style)


@dataclass
class Paragraph:
    runs: list[Run] = field(default_factory=lambda: [Run()])
    align: str = "left"
    line_spacing: float = 1.0
    space_before: float = 0.0
    space_after: float = 0.0


@dataclass
class ObjectBox:
    id: str = field(default_factory=uid)
    x: float = 60
    y: float = 60
    width: float = 350
    height: float = 110
    rotation: float = 0
    z: int = 0
    fill: str = "transparent"
    locked: bool = False
    opacity: float = 1.0
    parent_id: str = ""
    scale: float = 1.0


@dataclass
class GroupBox(ObjectBox):
    kind: str = "group"


@dataclass
class ShapeBox(ObjectBox):
    kind: str = "shape"
    shape: str = "rect"
    fill: str = "#dcebe5"
    stroke: str = "#39746b"
    stroke_width: float = 2


@dataclass
class ImageBox(ObjectBox):
    kind: str = "image"
    image_data: str = ""
    crop: list[float] | None = None
    flip_h: bool = False
    flip_v: bool = False
    aspect_locked: bool = True


@dataclass
class TextBox(ObjectBox):
    kind: str = "text"
    margin: float = 8.0
    writing_mode: str = "horizontal"
    paragraphs: list[Paragraph] = field(default_factory=lambda: [Paragraph([Run("번역문을 입력하세요")])])
    # These stay independent when the output box is moved or resized.
    source_text: str = ""
    source_rect: list[float] | None = None
    erase_rect: list[float] | None = None
    confidence: float = 100
    source_confirmed: bool = False
    source_method: str = ""
    target_origin: str = "manual"
    reviewed: bool = False
    candidate_text: str = ""
    candidate_source: str = ""
    translation_engine: str = ""
    candidate_engine: str = ""
    speaker: str = ""
    translation_context: str = ""
    join_source_lines: bool = True
    erase_enabled: bool = True
    erase_when_empty: bool = False
    erase_patch: str = ""
    erase_mask: str = ""
    link_mode: str = "auto"
    link_page_id: str = ""

    @property
    def text(self) -> str:
        return "\n".join("".join(r.text for r in p.runs) for p in self.paragraphs)


@dataclass
class BackgroundPatch:
    """A fixed original-page repair, independent of movable editing objects."""
    id: str = field(default_factory=uid)
    rect: list[int] = field(default_factory=list)
    patch: str = ""
    mask: str = ""


@dataclass
class Page:
    width: int = 900
    height: int = 1200
    id: str = field(default_factory=uid)
    name: str = "카드"
    asset: str = "assets/original.png"
    objects: list[TextBox | ShapeBox | ImageBox | GroupBox] = field(default_factory=list)
    ocr_done: bool = False
    width_pt: float = 0
    height_pt: float = 0
    source_file: str = ""
    background_patches: list[BackgroundPatch] = field(default_factory=list)
    # Optional rendering of the PDF with its native text objects removed.
    clean_asset: str = ""
    # Pixel rectangles [x, y, width, height] and stable destination page IDs.
    pdf_links: list[dict] = field(default_factory=list)
    native_chars: list[list] = field(default_factory=list)


@dataclass
class Project:
    id: str = field(default_factory=uid)
    name: str = "새 작업"
    version: int = 10
    pages: list[Page] = field(default_factory=lambda: [Page()])
    translation_engine: str = "chrome"
    glossary: list[dict] = field(default_factory=list)
    translation_memory: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Project:
        if data.get("version") not in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10):
            raise ValueError("지원하지 않는 프로젝트 버전입니다.")
        from .translation_quality import validate_translation_data
        validate_translation_data(data.get("translation_engine", "chrome"),
                                  data.get("glossary", []), data.get("translation_memory", []))
        if not re.fullmatch(r"[a-f0-9]{32}", data.get("id", "")):
            raise ValueError("프로젝트 식별자가 올바르지 않습니다.")
        if not 1 <= len(data.get("pages", [])) <= 200:
            raise ValueError("한 작품에 카드 1~200장을 담을 수 있습니다.")
        if data['version'] < 5 and len(data['pages']) != 1:
            raise ValueError("이전 버전의 작업 구성과 맞지 않습니다.")
        pages = []
        native_count = 0
        ids = set()
        page_ids, assets = set(), set()
        for p in data["pages"]:
            if not isinstance(p.get('id'), str) or not re.fullmatch(r'[a-f0-9]{32}', p['id']) or p['id'] in page_ids:
                raise ValueError("카드 식별자가 올바르지 않습니다.")
            page_ids.add(p['id'])
            if not isinstance(p.get('source_file', ''), str) or len(p.get('source_file', '')) > 32768:
                raise ValueError("원본 파일 정보가 올바르지 않습니다.")
            if not isinstance(p.get('name'), str) or len(p['name']) > 512:
                raise ValueError("카드 이름이 올바르지 않습니다.")
            for key in ('width_pt', 'height_pt'):
                value = p.get(key, 0)
                if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 14400:
                    raise ValueError("인쇄 크기가 올바르지 않습니다.")
            if bool(p.get('width_pt', 0)) != bool(p.get('height_pt', 0)):
                raise ValueError("인쇄 크기의 가로·세로가 필요합니다.")
            for k in ("width", "height"):
                if not isinstance(p[k], int) or not 1 <= p[k] <= 16000:
                    raise ValueError("원본 크기가 올바르지 않습니다.")
            if p["width"] * p["height"] > 80_000_000:
                raise ValueError("이미지가 너무 큽니다. 최대 8천만 픽셀까지 지원합니다.")
            if not isinstance(p.get('asset'), str) or not re.fullmatch(r'assets/(?:original|[a-f0-9]{32})\.png', p["asset"]) or p['asset'] in assets:
                raise ValueError("원본 참조가 올바르지 않습니다.")
            assets.add(p['asset'])
            clean_asset = p.get('clean_asset', '')
            if not isinstance(clean_asset, str) or (clean_asset and (
                    clean_asset != f"assets/{p['id']}_background.png" or clean_asset in assets)):
                raise ValueError("PDF 배경 참조가 올바르지 않습니다.")
            if clean_asset:
                assets.add(clean_asset)
            if len(p["objects"]) > 2000:
                raise ValueError("텍스트 상자가 너무 많습니다.")
            native_chars = p.get("native_chars", [])
            if not isinstance(native_chars, list) or len(native_chars) > 30000:
                raise ValueError("PDF 원문 정보가 너무 많거나 올바르지 않습니다.")
            native_count += len(native_chars)
            if native_count > 200000:
                raise ValueError("작품의 PDF 원문 정보가 너무 많습니다.")
            for entry in native_chars:
                if (not isinstance(entry, list) or len(entry) != 5 or
                        not isinstance(entry[0], str) or len(entry[0]) != 1 or
                        any(type(v) is not int or v < 0 for v in entry[1:]) or
                        min(entry[3:]) < 1 or entry[1]+entry[3] > p["width"] or entry[2]+entry[4] > p["height"]):
                    raise ValueError("PDF 원문 좌표가 올바르지 않습니다.")
            records = p.get("background_patches", [])
            if not isinstance(records, list) or len(records) > 2000:
                raise ValueError("배경 지우기 기록이 올바르지 않거나 너무 많습니다.")
            background_patches = []
            for record in records:
                if not isinstance(record, dict) or set(record) != {"id", "rect", "patch", "mask"}:
                    raise ValueError("배경 지우기 기록의 구성이 올바르지 않습니다.")
                key = record["id"]
                if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{32}", key) or key in ids:
                    raise ValueError("배경 지우기 식별자가 올바르지 않습니다.")
                ids.add(key)
                rect = record["rect"]
                if (not isinstance(rect, list) or len(rect) != 4 or
                        any(type(v) is not int for v in rect) or
                        min(rect[:2]) < 0 or min(rect[2:]) < 1 or
                        rect[0]+rect[2] > p['width'] or rect[1]+rect[3] > p['height'] or
                        rect[2]*rect[3] > 8_000_000):
                    raise ValueError("배경 지우기 범위가 올바르지 않습니다.")
                if any(not isinstance(record[k], str) or not record[k] or
                       len(record[k]) > 8_000_000 for k in ("patch", "mask")):
                    raise ValueError("배경 지우기 이미지가 없거나 너무 큽니다.")
                background_patches.append(BackgroundPatch(**record))
            objects = []
            for obj in p["objects"]:
                if obj["id"] in ids:
                    raise ValueError("중복 객체 식별자입니다.")
                ids.add(obj["id"])
                kind = obj.get("kind", "text")
                if kind not in ("text", "shape", "image", "group"):
                    raise ValueError("지원하지 않는 편집 대상입니다.")
                opacity = obj.get("opacity", 1)
                if not isinstance(opacity, (int, float)) or not math.isfinite(opacity) or not 0 <= opacity <= 1:
                    raise ValueError("투명도 값이 올바르지 않습니다.")
                if not isinstance(obj.get("locked", False), bool):
                    raise ValueError("잠금 값이 올바르지 않습니다.")
                parent_id = obj.get("parent_id", "")
                if not isinstance(parent_id, str):
                    raise ValueError("그룹 연결이 올바르지 않습니다.")
                scale = obj.get("scale", 1)
                if not isinstance(scale, (int, float)) or not math.isfinite(scale) or not .0001 <= scale <= 10000:
                    raise ValueError("대상 배율이 올바르지 않습니다.")
                if not isinstance(obj.get("z"), int) or abs(obj["z"]) > 100000:
                    raise ValueError("앞뒤 순서가 올바르지 않습니다.")
                if not isinstance(obj.get("source_text", ""), str) or not isinstance(obj.get("candidate_text", ""), str):
                    raise ValueError("원문/번역 정보가 올바르지 않습니다.")
                confidence = obj.get("confidence", 100)
                if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 100:
                    raise ValueError("원문 인식 정보가 올바르지 않습니다.")
                for key in ("source_rect", "erase_rect"):
                    rect = obj.get(key)
                    if rect is not None and (not isinstance(rect, list) or len(rect) != 4 or
                            not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 100000 for v in rect)):
                        raise ValueError("원문 영역 정보가 올바르지 않습니다.")
                for key in ("erase_patch", "erase_mask"):
                    if not isinstance(obj.get(key, ""), str) or len(obj.get(key, "")) > 8_000_000:
                        raise ValueError("원문 제거 기록이 올바르지 않습니다.")
                for k in ("x", "y", "width", "height", "rotation"):
                    if not isinstance(obj[k], (int, float)) or not math.isfinite(obj[k]) or abs(obj[k]) > 100000:
                        raise ValueError("객체 좌표가 올바르지 않습니다.")
                if obj["width"] < 24 or obj["height"] < 24:
                    raise ValueError("텍스트 상자 크기가 너무 작습니다.")
                if obj.get("fill", "transparent") != "transparent" and not re.fullmatch(r"#[a-fA-F0-9]{6}", obj["fill"]):
                    raise ValueError("배경 색이 올바르지 않습니다.")
                if kind == "group":
                    objects.append(GroupBox(**obj))
                    continue
                if kind == "shape":
                    if obj.get("shape") not in ("rect", "roundrect", "ellipse", "line", "arrow"):
                        raise ValueError("도형 종류가 올바르지 않습니다.")
                    if not re.fullmatch(r"#[a-fA-F0-9]{6}", obj.get("stroke", "")):
                        raise ValueError("테두리 색이 올바르지 않습니다.")
                    width = obj.get("stroke_width")
                    if not isinstance(width, (int, float)) or not math.isfinite(width) or not 0 <= width <= 30:
                        raise ValueError("선 두께가 올바르지 않습니다.")
                    objects.append(ShapeBox(**obj))
                    continue
                if kind == "image":
                    encoded = obj.get("image_data")
                    if not isinstance(encoded, str) or not encoded or len(encoded) > 12_000_000:
                        raise ValueError("삽입 이미지가 없거나 너무 큽니다.")
                    crop = obj.get("crop")
                    if crop is not None and (not isinstance(crop, list) or len(crop) != 4 or
                            not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1 for v in crop) or
                            crop[2] < .01 or crop[3] < .01 or crop[0]+crop[2] > 1.000001 or crop[1]+crop[3] > 1.000001):
                        raise ValueError("이미지 자르기 범위가 올바르지 않습니다.")
                    for key in ("flip_h", "flip_v", "aspect_locked"):
                        if not isinstance(obj.get(key, key == "aspect_locked"), bool):
                            raise ValueError("이미지 설정이 올바르지 않습니다.")
                    objects.append(ImageBox(**obj))
                    continue
                paragraphs = []
                if obj.get("source_method", "") not in ("", "ocr", "pdf", "manual"):
                    raise ValueError("원문 출처가 올바르지 않습니다.")
                for key in ("translation_engine", "candidate_engine"):
                    if obj.get(key, "") not in ("", "chrome", "local", "memory", "glossary"):
                        raise ValueError("번역 엔진 기록이 올바르지 않습니다.")
                for key, limit in (("speaker", 200), ("translation_context", 2000)):
                    if not isinstance(obj.get(key, ""), str) or len(obj.get(key, "")) > limit:
                        raise ValueError("화자 또는 문맥 정보가 올바르지 않습니다.")
                if not isinstance(obj.get("join_source_lines", True), bool):
                    raise ValueError("문단 입력 설정이 올바르지 않습니다.")
                if obj.get('link_mode', 'auto') not in ('auto', 'none', 'page'):
                    raise ValueError('페이지 링크 설정이 올바르지 않습니다.')
                target = obj.get('link_page_id', '')
                if not isinstance(target, str) or (target and not re.fullmatch(r'[a-f0-9]{32}', target)):
                    raise ValueError('페이지 링크 대상이 올바르지 않습니다.')
                for flag in ("erase_enabled", "erase_when_empty"):
                    if not isinstance(obj.get(flag, flag == "erase_enabled"), bool):
                        raise ValueError("원문 제거 설정이 올바르지 않습니다.")
                if obj.get("writing_mode", "horizontal") not in ("horizontal", "vertical-rl"):
                    raise ValueError("글쓰기 방향이 올바르지 않습니다.")
                margin = obj.get("margin", 8)
                if not isinstance(margin, (int, float)) or not math.isfinite(margin) or not 0 <= margin <= 200:
                    raise ValueError("안쪽 여백이 올바르지 않습니다.")
                for para in obj["paragraphs"]:
                    if para["align"] not in ("left", "center", "right"):
                        raise ValueError("문단 정렬이 올바르지 않습니다.")
                    for key, default, lower, upper in (("line_spacing", 1, .5, 4), ("space_before", 0, 0, 500), ("space_after", 0, 0, 500)):
                        value = para.get(key, default)
                        if not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
                            raise ValueError("문단 간격이 올바르지 않습니다.")
                    runs = []
                    for run in para["runs"]:
                        style = Style(**run["style"])
                        if not isinstance(style.family, str) or not style.family or len(style.family) > 256 or any(
                                not isinstance(getattr(style, flag), bool) for flag in ("bold", "italic", "underline", "strike")):
                            raise ValueError("글꼴 서식이 올바르지 않습니다.")
                        if not math.isfinite(style.size) or not 1 <= style.size <= 400:
                            raise ValueError("글자 크기가 올바르지 않습니다.")
                        if not re.fullmatch(r"#[a-fA-F0-9]{6}", style.color) or not isinstance(run["text"], str):
                            raise ValueError("글자 정보가 올바르지 않습니다.")
                        runs.append(Run(run["text"], style))
                    paragraphs.append(Paragraph(runs or [Run()], para["align"], para.get("line_spacing", 1), para.get("space_before", 0), para.get("space_after", 0)))
                objects.append(TextBox(**{**obj, "paragraphs": paragraphs or [Paragraph()]}))
            by_id = {obj.id: obj for obj in objects}
            for obj in objects:
                current, visited = obj, set()
                combined_scale = 1.0
                while True:
                    if current.id in visited or len(visited) > 8:
                        raise ValueError("그룹 연결이 순환하거나 8단계를 넘습니다.")
                    visited.add(current.id)
                    combined_scale *= current.scale
                    if not .0001 <= combined_scale <= 10000:
                        raise ValueError("중첩 그룹의 배율이 너무 크거나 작습니다.")
                    if not current.parent_id:
                        break
                    parent = by_id.get(current.parent_id)
                    if not isinstance(parent, GroupBox):
                        raise ValueError("연결된 그룹을 찾지 못했습니다.")
                    current = parent
            pages.append(Page(**{**p, "objects": objects, "background_patches": background_patches}))
        for page in pages:
            if not isinstance(page.pdf_links, list) or len(page.pdf_links) > 10000:
                raise ValueError('PDF 링크 정보가 올바르지 않거나 너무 많습니다.')
            for link in page.pdf_links:
                if not isinstance(link, dict) or set(link) != {'rect', 'page_id'} or link['page_id'] not in page_ids:
                    raise ValueError('PDF 링크 대상 페이지가 없습니다.')
                rect = link['rect']
                if (not isinstance(rect, list) or len(rect) != 4 or
                        any(type(v) not in (int, float) or not math.isfinite(v) for v in rect) or
                        min(rect[:2]) < 0 or min(rect[2:]) <= 0 or
                        rect[0]+rect[2] > page.width+.01 or rect[1]+rect[3] > page.height+.01):
                    raise ValueError('PDF 링크 영역이 올바르지 않습니다.')
            for obj in page.objects:
                if isinstance(obj, TextBox) and obj.link_mode == 'page' and obj.link_page_id not in page_ids:
                    raise ValueError('텍스트 링크 대상 페이지가 없습니다.')
        return cls(id=data["id"], name=data["name"], version=10, pages=pages,
                   translation_engine=data.get("translation_engine", "chrome"),
                   glossary=[dict(row, forbidden=list(row["forbidden"])) for row in data.get("glossary", [])],
                   translation_memory=[dict(row) for row in data.get("translation_memory", [])])
