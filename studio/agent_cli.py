"""File-based automation for ChiPDF. Translation is supplied by the calling agent."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from threading import Event
from types import SimpleNamespace


def source_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    from studio.storage import atomic_write
    atomic_write(Path(path), (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def bootstrap(root_arg, font_files=()):
    if getattr(sys, 'frozen', False):
        root = Path(sys._MEIPASS)
        from studio.runtime import protect_running_app
        protect_running_app(Path(sys.executable).parent)
    else:
        root = find_source(root_arg)
        sys.path.insert(0, str(root))
        sys.path.insert(0, str(root / '.deps'))
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    QApplication.setAttribute(Qt.AA_Use96Dpi)
    app = QApplication.instance() or QApplication(['chipdf-agent'])
    load_fonts(font_files)
    return root, app


def find_source(root_arg):
    candidates = ([Path(root_arg)] if root_arg else [])
    if os.environ.get('CHIPDF_ROOT'):
        candidates.append(Path(os.environ['CHIPDF_ROOT']))
    candidates.extend(Path(__file__).resolve().parents)
    root = next((p.resolve() for p in candidates if (p / 'studio/document_io.py').is_file()), None)
    if root is None:
        raise ValueError('ChiPDF source not found. Supply --chipdf-root or CHIPDF_ROOT.')
    return root


def load_fonts(font_files):
    # Windows' offscreen Qt plugin does not enumerate system fonts.
    from PySide6.QtGui import QFont, QFontDatabase
    if sys.platform == 'win32':
        font_dir = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Fonts'
        for name in ('malgun.ttf', 'malgunbd.ttf', 'msgothic.ttc'):
            path = font_dir / name
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
        QFont.insertSubstitution('맑은 고딕', 'Malgun Gothic')
    for path in font_files:
        if QFontDatabase.addApplicationFont(str(Path(path).resolve())) < 0:
            raise ValueError(f'Could not load font: {path}')


def page_indices(spec, count):
    if not spec:
        return list(range(count))
    result = set()
    for part in spec.split(','):
        bounds = part.strip().split('-')
        if len(bounds) not in (1, 2):
            raise ValueError('Use --pages 1-3,5 (one-based).')
        first, last = int(bounds[0]), int(bounds[-1])
        if not 1 <= first <= last <= count:
            raise ValueError(f'Page range outside 1..{count}: {part}')
        result.update(range(first - 1, last))
    return sorted(result)


def output_path(path, inputs=(), overwrite=False):
    path = Path(path).resolve()
    if path in {Path(p).resolve() for p in inputs}:
        raise ValueError('Output must differ from input files.')
    if path.exists() and not overwrite:
        raise ValueError(f'Output already exists: {path}. Use a new path or --overwrite.')
    return path


def load(path):
    from studio.storage import load_bundle
    from studio.document_io import validate_bundle
    project, assets = load_bundle(Path(path))
    validate_bundle(project, assets)
    return project, assets


def text_objects(page):
    from studio.model import TextBox
    return [o for o in page.objects if isinstance(o, TextBox) and o.source_text.strip()]


def recognize_page(page, assets, vertical):
    from studio.recognition import recognize
    from studio.native_source import prefer_native_source
    from studio.model import TextBox, Paragraph, Run, Style
    from studio.workflow import overlaps
    regions = recognize(assets[page.asset], Event(), lambda m: print(m, file=sys.stderr),
                        vertical=vertical, clean_background=assets.get(page.clean_asset))
    existing = [o.source_rect for o in text_objects(page) if o.source_rect]
    for region in regions:
        region = prefer_native_source(region, page.native_chars)
        if any(overlaps(region.rect, rect) for rect in existing):
            continue
        x, y, w, h = region.rect
        box = TextBox(x=max(0, x-6), y=max(0, y-5), width=max(24, w+12),
                      height=max(32, h+12), z=len(page.objects),
                      paragraphs=[Paragraph([Run('', Style(size=max(9, min(28, region.line_height*.68))))])],
                      source_text=region.text, source_rect=list(region.rect),
                      confidence=max(0, min(100, region.confidence)), source_method=region.source_method,
                      erase_rect=region.erase_rect, erase_patch=region.patch, erase_mask=region.mask)
        page.objects.append(box)
        existing.append(region.rect)
    page.ocr_done = True


def snapshot(project, assets, indices, destination):
    """Save source pages, source crops, and editable translations with stable IDs."""
    from PySide6.QtGui import QImage
    from studio.storage import atomic_write
    from studio.document_io import png_data
    destination.mkdir(parents=True, exist_ok=True)
    entries, pages = [], []
    for index in indices:
        page = project.pages[index]
        original = destination / f'original-{index+1:03d}.png'
        atomic_write(original, assets[page.asset])
        image = QImage.fromData(assets[page.asset], 'PNG')
        pages.append({'page': index+1, 'page_id': page.id, 'image': str(original),
                      'width': page.width, 'height': page.height,
                      'native_character_count': len(page.native_chars),
                      'region_count': len(text_objects(page))})
        for obj in text_objects(page):
            crop_path = None
            if obj.source_rect:
                x, y, w, h = obj.source_rect
                x0, y0 = max(0, math.floor(x)), max(0, math.floor(y))
                x1, y1 = min(page.width, math.ceil(x+w)), min(page.height, math.ceil(y+h))
                if x1 > x0 and y1 > y0:
                    crop_path = destination / f'crop-{obj.id}.png'
                    atomic_write(crop_path, png_data(image.copy(x0, y0, x1-x0, y1-y0)))
            entries.append({'page': index+1, 'page_id': page.id, 'id': obj.id,
                            'source': obj.source_text, 'source_sha256': source_hash(obj.source_text),
                            'source_method': obj.source_method, 'confidence': obj.confidence,
                            'speaker': obj.speaker, 'context': obj.translation_context,
                            'source_rect': obj.source_rect, 'crop': str(crop_path) if crop_path else None,
                            'target': obj.text})
    result = {'schema': 'chipdf-ja-ko/1', 'project_id': project.id,
              'glossary': project.glossary, 'translation_memory': project.translation_memory,
              'pages': pages, 'entries': entries}
    write_json(destination / 'sources.json', result)
    return result


def inspect_layout(project, indices):
    from studio.canvas import TextItem
    from studio.translation_quality import quality_issues
    from PySide6.QtGui import QRawFont
    issues = []
    for index in indices:
        page = project.pages[index]
        boxes = text_objects(page)
        if not boxes:
            issues.append({'page': index+1, 'code': 'no_regions', 'blocking': True,
                           'message': 'No source regions detected; inspect the original page.'})
        for obj in boxes:
            def add(code, message, blocking=True):
                issues.append({'page': index+1, 'id': obj.id, 'code': code,
                               'blocking': blocking, 'message': message})
            if not obj.text.strip():
                add('untranslated', 'Translation is empty.')
                continue
            item = TextItem(obj, SimpleNamespace(changed=lambda: None))
            raw_font = QRawFont.fromFont(item.document().defaultFont())
            if any('\uac00' <= char <= '\ud7a3' and not raw_font.supportsCharacter(ord(char)) for char in set(obj.text)):
                add('missing_font', 'Selected font cannot render the Korean text; load a Korean font with --font-file.')
            if item.has_overflow():
                add('overflow', 'Text is clipped inside its box.')
            bounds = item.mapRectToScene(item.boundingRect())
            if bounds.left() < 0 or bounds.top() < 0 or bounds.right() > page.width+1 or bounds.bottom() > page.height+1:
                add('outside_page', 'Text box extends beyond the page.')
            if not obj.erase_enabled or not obj.erase_patch or not obj.erase_mask:
                add('missing_erase', 'Japanese source has no enabled background repair.')
            if obj.source_method == 'ocr' and obj.confidence < 80 and not obj.source_confirmed:
                add('low_confidence', 'Compare OCR with the source crop.', False)
            for message in quality_issues(obj.source_text, obj.text, project.glossary):
                add('translation_check', message, False)
    return {'project_id': project.id, 'pages': [i+1 for i in indices],
            'blocking_count': sum(i['blocking'] for i in issues), 'issues': issues}


def previews(project, assets, indices, destination):
    from studio.document_io import render_page, png_data
    from studio.storage import atomic_write
    destination.mkdir(parents=True, exist_ok=True)
    for index in indices:
        page = project.pages[index]
        atomic_write(destination / f'page-{index+1:03d}.png', png_data(render_page(page, assets[page.asset])))
    report = inspect_layout(project, indices)
    write_json(destination / 'report.json', report)
    return report


def prepare(args):
    from studio.document_io import import_files
    from studio.storage import save_project
    destination = output_path(args.output)
    if destination.exists():
        raise ValueError('Preparation requires a new output directory.')
    project, assets, _ = import_files([args.input], progress=lambda m: print(m, file=sys.stderr))
    indices = page_indices(args.pages, len(project.pages))
    for index in indices:
        page = project.pages[index]
        if not page.ocr_done and not text_objects(page):
            recognize_page(page, assets, args.vertical)
    destination.mkdir(parents=True)
    save_project(destination / 'source.twproj', project, assets)
    result = snapshot(project, assets, indices, destination)
    write_json(destination / 'translations.json', {
        'schema': result['schema'], 'project_id': project.id,
        'entries': [{k: row[k] for k in ('id', 'source_sha256', 'target')} for row in result['entries']]})
    return {'project': str(destination / 'source.twproj'), 'sources': str(destination / 'sources.json'),
            'translations': str(destination / 'translations.json'), 'regions': len(result['entries']),
            'pages': result['pages']}


def apply(args):
    from studio.model import Project, Paragraph, Run
    from studio.storage import save_project
    from studio.canvas import TextItem
    from studio.richtext import populate
    project, assets = load(args.project)
    data = read_json(args.translations)
    if data.get('schema') != 'chipdf-ja-ko/1' or data.get('project_id') != project.id:
        raise ValueError('Translation schema/project ID does not match.')
    if not isinstance(data.get('entries'), list) or not data['entries']:
        raise ValueError('Supply a nonempty entries array.')
    output = output_path(args.output, (args.project, args.translations), args.overwrite)
    objects = {o.id: (index, o) for index, page in enumerate(project.pages) for o in text_objects(page)}
    seen, changed = set(), set()
    for row in data['entries']:
        key = row.get('id')
        if key not in objects or key in seen:
            raise ValueError(f'Unknown or duplicate text ID: {key}')
        seen.add(key)
        index, obj = objects[key]
        if row.get('source_sha256') != source_hash(obj.source_text):
            raise ValueError(f'Stale source text for {key}; prepare a fresh translation snapshot.')
        target = row.get('target')
        if not isinstance(target, str) or not target.strip() or len(target) > 120000:
            raise ValueError(f'Missing or oversized translation for {key}. Omit pending entries for a partial batch.')
        if obj.locked or obj.parent_id:
            raise ValueError(f'Locked/grouped source box requires editor review: {key}')
        style = deepcopy(obj.paragraphs[0].runs[0].style)
        layout = row.get('layout', {})
        if not isinstance(layout, dict) or set(layout) - {'rect', 'font_size', 'font_family', 'align', 'writing_mode', 'vertical_align'}:
            raise ValueError(f'Unsupported layout fields for {key}')
        if 'rect' in layout:
            rect = layout['rect']
            if not isinstance(rect, list) or len(rect) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in rect):
                raise ValueError('layout.rect must be [x,y,width,height].')
            obj.x, obj.y, obj.width, obj.height = rect
        if 'font_size' in layout:
            size = layout['font_size']
            if type(size) not in (int, float) or not math.isfinite(size) or not 9 <= size <= 300:
                raise ValueError('font_size must be between 9 and 300.')
            style.size = size
        if 'font_family' in layout:
            style.family = layout['font_family']
        if 'writing_mode' in layout:
            obj.writing_mode = layout['writing_mode']
        if 'vertical_align' in layout:
            obj.vertical_align = layout['vertical_align']
        align = layout.get('align', obj.paragraphs[0].align)
        obj.paragraphs = [Paragraph([Run(line, deepcopy(style))], align=align) for line in target.split('\n')]
        # Externally supplied GPT text is manual text,
        # while its provider is recorded in the companion JSON, not an invented engine enum.
        obj.target_origin = 'manual'
        obj.translation_engine = ''
        obj.reviewed = False
        obj.candidate_text = obj.candidate_source = obj.candidate_engine = ''
        if 'corrected_source' in row:
            if not isinstance(row['corrected_source'], str) or not row['corrected_source'].strip() or len(row['corrected_source']) > 30000:
                raise ValueError('corrected_source must be nonempty text of at most 30,000 characters.')
            obj.source_text = row['corrected_source']
            obj.source_method = 'manual'
            obj.source_confirmed = True
        Project.from_dict(project.to_dict())
        if not args.no_fit:
            item = TextItem(obj, SimpleNamespace(changed=lambda: None))
            while item.has_overflow() and obj.paragraphs[0].runs[0].style.size > args.min_font_size:
                for paragraph in obj.paragraphs:
                    for run in paragraph.runs:
                        run.style.size = max(args.min_font_size, run.style.size - .5)
                populate(item.document(), obj.paragraphs, obj.margin)
                item.setTextWidth(obj.width)
        changed.add(index)
    Project.from_dict(project.to_dict())
    save_project(output, project, assets)
    indices = sorted(changed)
    report = previews(project, assets, indices, Path(str(output) + '.preview'))
    write_json(Path(str(output) + '.translations.json'), {**data, 'provider': 'external-agent'})
    snapshot(project, assets, indices, Path(str(output) + '.sources'))
    return {'project': str(output), 'applied': len(seen), 'preview': str(output) + '.preview',
            'blocking_count': report['blocking_count']}


def preview(args):
    project, assets = load(args.project)
    return previews(project, assets, page_indices(args.pages, len(project.pages)), Path(args.output).resolve())


def export(args):
    from studio.document_io import export_collection
    project, assets = load(args.project)
    indices = page_indices(args.pages, len(project.pages))
    output = output_path(args.output, (args.project,), args.overwrite)
    report = previews(project, assets, indices, Path(str(output) + '.preview'))
    if report['blocking_count'] and not args.allow_incomplete:
        raise ValueError(f"Export blocked by {report['blocking_count']} layout/source issues. See {output}.preview/report.json")
    exported = {}
    export_collection(project, assets, indices, output, 'pdf', text_mode=args.text_mode, report=exported)
    # Pages without an embedded source PDF are exported as whole-page images,
    # which is usually what makes a localized PDF many times larger.
    raster = [indices[i]+1 for i in exported.get('raster_pages', [])]
    image_text = [indices[i]+1 for i in exported.get('image_text_pages', [])]
    sources = {project.pages[i].pdf_asset for i in indices} - {''}
    source_bytes = sum(len(assets[key]) for key in sources)
    result = {'pdf': str(output), 'preview': str(output) + '.preview', 'report': report,
              'text_mode': args.text_mode, 'raster_pages': raster, 'image_text_pages': image_text,
              'removed_source_text': exported.get('removed_source_text', 0),
              'pdf_bytes': output.stat().st_size}
    if source_bytes:
        result['size_ratio'] = round(output.stat().st_size/source_bytes, 2)
    warnings = []
    if raster:
        warnings.append(f'{len(raster)} page(s) have no embedded source PDF and were exported as '
                        'page images. Keep pdf_asset/pdf_page in the project to preserve the original.')
    if image_text:
        warnings.append(f'{len(image_text)} page(s) did not match the editor rendering as real text and '
                        'keep their Korean text as images. Check fonts (--font-file) on those pages.')
    if warnings:
        result['warning'] = ' '.join(warnings)
    return result


def main(argv=None):
    # PyInstaller --windowed has no stdout/stderr. Result JSON is the IPC channel.
    import io
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result-json', type=Path, help='Write success/error JSON for windowed executables.')
    parser.add_argument('--chipdf-root', type=Path)
    parser.add_argument('--font-file', action='append', default=[], type=Path,
                        help='Load a TTF/TTC/OTF font for offscreen rendering (repeatable).')
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('info', help='Report automation capabilities without opening the editor.')
    p.set_defaults(run=lambda args: {'app': 'ChiPDF', 'protocol': 'chipdf-ja-ko/1',
                                   'commands': ['prepare', 'apply', 'preview', 'export'],
                                   'version': __import__('studio').__version__})
    p = commands.add_parser('prepare', help='Import, recognize, and write source crops/JSON.')
    p.add_argument('input', type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--pages', help='One-based pages, e.g. 1-3,5. Import limits still apply to the entire input.')
    p.add_argument('--vertical', action='store_true', help='Use vertical Japanese OCR on selected pages.')
    p.set_defaults(run=prepare)
    p = commands.add_parser('apply', help='Apply external translations and generate preview/report.')
    p.add_argument('project', type=Path)
    p.add_argument('translations', type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--min-font-size', type=float, default=9)
    p.add_argument('--no-fit', action='store_true')
    p.add_argument('--overwrite', action='store_true')
    p.set_defaults(run=apply)
    p = commands.add_parser('preview', help='Render selected pages and check layout.')
    p.add_argument('project', type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--pages')
    p.set_defaults(run=preview)
    p = commands.add_parser('export', help='Export a rendered Korean PDF after checking layout.')
    p.add_argument('project', type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--pages')
    p.add_argument('--overwrite', action='store_true')
    p.add_argument('--allow-incomplete', action='store_true', help='Explicitly export despite blocking report issues.')
    p.add_argument('--text-mode', choices=('text', 'image'), default='text',
                   help='text: delete translated source text and write Korean as real text (default); '
                        'image: previous output with Korean drawn as images.')
    p.set_defaults(run=export)
    args = parser.parse_args(argv)
    try:
        if hasattr(args, 'min_font_size') and (not math.isfinite(args.min_font_size) or not 9 <= args.min_font_size <= 300):
            raise ValueError('--min-font-size must be between 9 and 300.')
        if args.command != 'info':
            root, app = bootstrap(args.chipdf_root, args.font_file)
        result = args.run(args)
        if args.result_json:
            write_json(args.result_json, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        error = {'error': str(exc), 'type': type(exc).__name__}
        if args.result_json:
            write_json(args.result_json, error)
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
