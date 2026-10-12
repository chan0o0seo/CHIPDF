"""Inspect and validate observed CCFOLIA 1.1.0 ZIPs; no translation or live upload."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

HASH_NAME = re.compile(r'^[0-9a-f]{64}\.[A-Za-z0-9]+$')
TOKEN = re.compile(rb'0\.([0-9a-f]{64})')


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


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inspect', 'validate'))
    parser.add_argument('input', type=Path)
    parser.add_argument('--original', type=Path, help='Include JSON structural diff and asset byte changes.')
    parser.add_argument('--output', type=Path, required=True, help='Report path outside import ZIP.')
    args = parser.parse_args()
    try:
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
        print(json.dumps({'report': str(args.output.resolve()), 'errors': len(report['errors']),
                          'warnings': len(report['warnings']), 'assets': len(report['assets']),
                          'actual_ccfolia_import_tested': False}, ensure_ascii=False))
        return 1 if args.command == 'validate' and report['errors'] else 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
