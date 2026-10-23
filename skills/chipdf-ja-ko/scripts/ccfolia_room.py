"""Inspect, rebuild and validate observed CCFOLIA 1.1.0 ZIPs; no translation or live upload."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

HASH_NAME = re.compile(r'^[0-9a-f]{64}\.[A-Za-z0-9]+$')
TOKEN = re.compile(rb'0\.([0-9a-f]{64})')
JAPANESE = re.compile('[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]')
SIGNATURES = {'png': (b'\x89PNG\r\n\x1a\n',), 'jpg': (b'\xff\xd8\xff',), 'jpeg': (b'\xff\xd8\xff',),
              'gif': (b'GIF87a', b'GIF89a'), 'webp': (b'RIFF',)}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pointer(path, key):
    return path + '/' + str(key).replace('~', '~0').replace('/', '~1')


def leaves(value, path=''):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from leaves(item, pointer(path, key))
    elif isinstance(value, list):
        for key, item in enumerate(value):
            yield from leaves(item, pointer(path, key))
    else:
        yield path, value


def changes(before, after, path=''):
    if type(before) is not type(after):
        yield {'path': path, 'before': before, 'after': after}
    elif isinstance(before, dict):
        for key in sorted(before.keys() | after.keys()):
            p = pointer(path, key)
            if key not in before:
                yield {'path': p, 'added': after[key]}
            elif key not in after:
                yield {'path': p, 'removed': before[key]}
            else:
                yield from changes(before[key], after[key], p)
    elif isinstance(before, list):
        if len(before) != len(after):
            yield {'path': path, 'before': before, 'after': after}
        else:
            for key, (a, b) in enumerate(zip(before, after)):
                yield from changes(a, b, pointer(path, key))
    elif before != after:
        yield {'path': path, 'before': before, 'after': after}


def load(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate ZIP member names')
        for name in names:
            parts = PurePosixPath(name).parts
            if name.startswith('/') or '\\' in name or '..' in parts or (parts and ':' in parts[0]):
                raise ValueError('Unsafe ZIP member path: ' + name)
        corrupt = archive.testzip()
        if corrupt:
            raise ValueError('ZIP CRC failure: ' + corrupt)
        data = archive.read('__data.json')
        document = json.loads(data.decode('utf-8-sig'))
        if not isinstance(document, dict) or not isinstance(document.get('entities'), dict) or not isinstance(document.get('resources'), dict):
            raise ValueError('Unsupported room structure; inspect it without applying this profile')
        resources = document['resources']
        errors, warnings, assets = [], [], []
        if not isinstance(document.get('meta'), dict) or document['meta'].get('version') != '1.1.0':
            errors.append('Unsupported meta.version; only observed 1.1.0 profile is validated')
        token = archive.read('.token') if '.token' in names else b''
        match = TOKEN.fullmatch(token)
        if not match:
            errors.append('Missing/unsupported .token format; expected 0.<sha256>')
        elif match[1].decode('ascii') != sha(data):
            errors.append('.token checksum does not match exact __data.json bytes')
        for name, metadata in resources.items():
            if name not in names:
                errors.append('Resource member missing: ' + name)
                continue
            payload = archive.read(name)
            digest = sha(payload)
            if HASH_NAME.fullmatch(name) and name.split('.')[0] != digest:
                errors.append('Resource filename hash differs from bytes: ' + name)
            if not HASH_NAME.fullmatch(name):
                warnings.append('Non-hash resource filename; convention not validated: ' + name)
            assets.append({'name': name, 'bytes': len(payload), 'sha256': digest, 'metadata': metadata})
        strings, refs = [], []
        for p, value in leaves(document['entities'], '/entities'):
            if not isinstance(value, str):
                continue
            field = p.rsplit('/', 1)[-1]
            is_ref = value in resources or HASH_NAME.fullmatch(value) is not None
            if is_ref:
                refs.append({'path': p, 'resource': value})
                if value not in resources:
                    errors.append('Local resource reference missing from resources: ' + p)
            elif field.lower().endswith('url') and value and not re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', value):
                if value in names:
                    errors.append('Local URL lacks resource metadata: ' + p)
                else:
                    warnings.append('Unresolved local/relative URL: ' + p)
            if is_ref or field.lower().endswith('url'):
                category = 'resource_or_url'
            elif value.startswith('/') or '/clickAction/' in p or field in ('commands', 'command'):
                category = 'command_or_action_review'
            elif field in ('name', 'text', 'memo', 'description', 'label', 'title'):
                category = 'display_text_candidate'
            else:
                category = 'other_string_review'
            strings.append({'path': p, 'source': value, 'source_sha256': sha(value.encode('utf-8')),
                            'category': category, 'has_kana': bool(re.search('[\u3040-\u30ff]', value))})
        summary = {key: {'type': type(value).__name__, 'count': len(value) if isinstance(value, (dict, list)) else None}
                   for key, value in document['entities'].items()}
        return document, {'schema': 'chipdf-ccfolia-inspection/1', 'input': str(path.resolve()),
                          'profile': 'observed-1.1.0', 'data_sha256': sha(data),
                          'zip_members': len(names), 'entities': summary, 'assets': assets,
                          'resource_references': refs, 'strings': strings,
                          'errors': errors, 'warnings': warnings,
                          'zip_crc_checked': True, 'actual_ccfolia_import_tested': False,
                          'image_decode_tested': False,
                          'note': 'Categories are review hints, not permission to translate. Kana detection excludes kanji-only Japanese. Review commands, images, and all structural diffs.'}


def template(report):
    """Translation table rows for every non-reference string that contains Japanese."""
    entries = [{'path': s['path'], 'source': s['source'], 'source_sha256': s['source_sha256'],
                'category': s['category'], 'decision': '', 'target': ''}
               for s in report['strings'] if s['category'] != 'resource_or_url' and JAPANESE.search(s['source'])]
    return {'schema': 'chipdf-ccfolia-room-translations/1', 'input': report['input'],
            'data_sha256': report['data_sha256'], 'entries': entries,
            'note': 'decision: translate or preserve. Rows left undecided or without target block build.'}


def locate(document, path):
    keys = [part.replace('~1', '/').replace('~0', '~') for part in path[1:].split('/')]
    parent = document
    try:
        for key in keys[:-1]:
            parent = parent[int(key)] if isinstance(parent, list) else parent[key]
        last = int(keys[-1]) if isinstance(parent, list) else keys[-1]
        parent[last]
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError('Path not found in room data: ' + path) from None
    return parent, last


def rename_refs(value, renames):
    if isinstance(value, dict):
        return {key: rename_refs(item, renames) for key, item in value.items()}
    if isinstance(value, list):
        return [rename_refs(item, renames) for item in value]
    return renames.get(value, value) if isinstance(value, str) else value


def scene_names(document):
    return {value for p, value in leaves(document['entities'], '/entities')
            if isinstance(value, str) and re.search(r'/scenes/[^/]+/name$', p)}


def translate_strings(document, table_path):
    table = json.loads(table_path.read_text(encoding='utf-8-sig'))
    entries = table.get('entries') if isinstance(table, dict) else None
    if not isinstance(entries, list):
        raise ValueError('Room translations need an "entries" list')
    applied, preserved, missing, renamed, seen = [], [], [], {}, set()
    for entry in entries:
        path = entry.get('path') if isinstance(entry, dict) else None
        if not isinstance(path, str) or not path.startswith('/entities/'):
            raise ValueError('Only /entities/... string paths can be translated: %r' % (path,))
        if path in seen:
            raise ValueError('Duplicate translation path: ' + path)
        seen.add(path)
        target = entry.get('target')
        decision = entry.get('decision') or ('translate' if target else '')
        if decision not in ('translate', 'preserve', ''):
            raise ValueError('decision must be translate or preserve: ' + path)
        parent, key = locate(document, path)
        current = parent[key]
        if not isinstance(current, str):
            raise ValueError('Not a string value: ' + path)
        if entry.get('source_sha256') != sha(current.encode('utf-8')):
            raise ValueError('Source text differs from the inspected text: ' + path)
        if decision == 'preserve':
            preserved.append(path)
        elif decision == '' or not isinstance(target, str) or not target.strip():
            missing.append(path)
        else:
            parent[key] = target
            applied.append(path)
            if re.search(r'/scenes/[^/]+/name$', path) and target != current:
                renamed[current] = target
    return applied, preserved, missing, renamed


def replace_assets(document, members, map_path):
    mapping = json.loads(map_path.read_text(encoding='utf-8-sig'))
    replacements = mapping.get('replacements') if isinstance(mapping, dict) else None
    if not isinstance(replacements, list):
        raise ValueError('Asset map needs a "replacements" list')
    resources, renames, payloads = document['resources'], {}, {}
    for item in replacements:
        old, file = (item.get('name'), item.get('file')) if isinstance(item, dict) else (None, None)
        if old not in resources or old not in members:
            raise ValueError('Asset map names an unknown resource: %r' % (old,))
        if old in renames or old in payloads:
            raise ValueError('Resource replaced twice: ' + old)
        path = Path(file)
        payload = (path if path.is_absolute() else map_path.parent / path).read_bytes()
        extension = old.rsplit('.', 1)[-1] if '.' in old else ''
        signatures = SIGNATURES.get(extension.lower())
        if signatures and (not payload.startswith(signatures) or (extension.lower() == 'webp' and payload[8:12] != b'WEBP')):
            raise ValueError('%s is not %s data; save the translated image in the original format' % (file, extension))
        new = sha(payload) + '.' + extension
        if new in members and new != old and members[new] != payload:
            raise ValueError('Existing member has the same name but other bytes: ' + new)
        if new != old:
            renames[old] = new
        payloads[old] = payload
    rebuilt = {}
    for name, metadata in resources.items():
        target = renames.get(name, name)
        if target in rebuilt and rebuilt[target] != metadata:
            raise ValueError('Merged resources have different metadata: ' + target)
        rebuilt.setdefault(target, metadata)
    document['resources'] = rebuilt
    document['entities'] = rename_refs(document['entities'], renames)
    if renames:
        stale = re.compile('|'.join(map(re.escape, renames)))
        embedded = [p for p, value in leaves(document['entities'], '/entities') if isinstance(value, str) and stale.search(value)]
        if embedded:
            raise ValueError('Old asset names remain inside longer strings; update them by hand: ' + ', '.join(embedded[:10]))
    return renames, payloads


def build(args):
    if not (args.translations or args.assets):
        raise ValueError('build needs --translations and/or --assets')
    if args.output.resolve() == args.input.resolve():
        raise ValueError('Write the Korean room to a new ZIP; the original stays untouched')
    if args.output.exists() and not args.overwrite:
        raise ValueError('Output exists; pass --overwrite to replace it: ' + str(args.output))
    document, original_report = load(args.input)
    with zipfile.ZipFile(args.input) as archive:
        infos = archive.infolist()
        members = {info.filename: archive.read(info) for info in infos}
    if not TOKEN.fullmatch(members.get('.token', b'')):
        raise ValueError('Unsupported .token format; inspect the room before rebuilding it')
    compact = members['__data.json'] == json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    applied, preserved, missing, renamed = translate_strings(document, args.translations) if args.translations else ([], [], [], {})
    if missing and not args.allow_incomplete:
        raise ValueError('%d rows are undecided or have no target: %s' % (len(missing), ', '.join(missing[:10])))
    names = scene_names(document)
    broken = [p for p, value in leaves(document['entities'], '/entities') if isinstance(value, str)
              for old in renamed if old not in names and re.search(r'/scene[ \t]+' + re.escape(old) + r'(?=\s|$)', value)]
    if broken:
        raise ValueError('/scene commands still use renamed scene names: ' + ', '.join(sorted(set(broken))[:10]))
    renames, payloads = replace_assets(document, members, args.assets) if args.assets else ({}, {})
    data = json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    replaced = {'__data.json': data, '.token': b'0.' + sha(data).encode('ascii')}
    temporary = args.output.with_name(args.output.name + '.partial')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    written = set()
    with zipfile.ZipFile(temporary, 'w') as archive:
        for info in infos:
            name = renames.get(info.filename, info.filename)
            if name in written:
                continue
            written.add(name)
            copy = zipfile.ZipInfo(name, info.date_time)
            copy.compress_type, copy.external_attr, copy.create_system = info.compress_type, info.external_attr, info.create_system
            archive.writestr(copy, replaced.get(name, payloads.get(info.filename, members[info.filename])))
    temporary.replace(args.output)
    rebuilt, report = load(args.output)
    original_strings = {s['path'] for s in original_report['strings']}
    untouched = [s['path'] for s in report['strings'] if s['path'] in original_strings and s['category'] != 'resource_or_url'
                 and JAPANESE.search(s['source']) and s['path'] not in set(preserved)]
    return {'schema': 'chipdf-ccfolia-build/1', 'input': str(args.input.resolve()), 'output': str(args.output.resolve()),
            'strings_translated': len(applied), 'strings_preserved': len(preserved), 'strings_missing': missing,
            'renamed_scenes': renamed, 'asset_renames': renames, 'data_was_compact': compact,
            'japanese_strings_remaining': untouched, 'errors': report['errors'], 'warnings': report['warnings'],
            'original_errors': original_report['errors'], 'json_changes': list(changes(json.loads(members['__data.json'].decode('utf-8-sig')), rebuilt)),
            'structural_diff_reviewed': False, 'zip_crc_checked': True, 'image_decode_tested': False,
            'actual_ccfolia_import_tested': False,
            'note': 'Remaining Japanese strings are review hints: intentionally kept names or commands are fine, others are unfinished.'}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inspect', 'validate', 'build'))
    parser.add_argument('input', type=Path)
    parser.add_argument('--original', type=Path, help='Include JSON structural diff and asset byte changes.')
    parser.add_argument('--output', type=Path, required=True, help='Report path outside import ZIP; for build, the new room ZIP.')
    parser.add_argument('--template', type=Path, help='inspect: also write a room-translations.json to fill in.')
    parser.add_argument('--translations', type=Path, help='build: reviewed room-translations.json.')
    parser.add_argument('--assets', type=Path, help='build: {"replacements": [{"name": <resource>, "file": <translated image>}]}.')
    parser.add_argument('--report', type=Path, help='build: report path outside the room ZIP.')
    parser.add_argument('--allow-incomplete', action='store_true', help='build: leave undecided rows unchanged.')
    parser.add_argument('--overwrite', action='store_true', help='build: replace an existing output ZIP.')
    args = parser.parse_args()
    try:
        if args.command == 'build':
            if not args.report or args.report.resolve() in {args.input.resolve(), args.output.resolve()}:
                raise ValueError('build needs a --report path apart from the ZIPs')
            report = build(args)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(json.dumps({'output': report['output'], 'report': str(args.report.resolve()), 'errors': len(report['errors']),
                              'strings_translated': report['strings_translated'], 'assets_replaced': len(report['asset_renames']),
                              'japanese_strings_remaining': len(report['japanese_strings_remaining']),
                              'actual_ccfolia_import_tested': False}, ensure_ascii=False))
            return 1 if report['errors'] else 0
        if args.output.resolve() in {args.input.resolve(), args.original.resolve() if args.original else args.input.resolve()}:
            raise ValueError('Report output must differ from input and original ZIP paths')
        document, report = load(args.input)
        if args.original:
            original, original_report = load(args.original)
            report['original_errors'] = original_report['errors']
            report['json_changes'] = list(changes(original, document))
            old_assets = {a['name']: a['sha256'] for a in original_report['assets']}
            new_assets = {a['name']: a['sha256'] for a in report['assets']}
            report['asset_changes'] = {'added': sorted(new_assets.keys() - old_assets.keys()),
                                       'removed': sorted(old_assets.keys() - new_assets.keys()),
                                       'same_name_changed_bytes': sorted(k for k in old_assets.keys() & new_assets.keys() if old_assets[k] != new_assets[k])}
            report['structural_diff_reviewed'] = False
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if args.template:
            if args.template.exists():
                raise ValueError('Template exists; keep the reviewed table and remove it first to regenerate: ' + str(args.template))
            args.template.write_text(json.dumps(template(report), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'report': str(args.output.resolve()), 'errors': len(report['errors']),
                          'warnings': len(report['warnings']), 'assets': len(report['assets']),
                          'template': str(args.template.resolve()) if args.template else None,
                          'actual_ccfolia_import_tested': False}, ensure_ascii=False))
        return 1 if args.command == 'validate' and report['errors'] else 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
