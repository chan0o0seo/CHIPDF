"""List local Korean fonts and verify text glyphs. Python standard library only."""
import argparse
import bisect
import json
import os
from pathlib import Path
import struct
import sys


def u16(data, offset):
    return struct.unpack_from('>H', data, offset)[0]


def u32(data, offset):
    return struct.unpack_from('>I', data, offset)[0]


def default_dirs():
    if sys.platform == 'win32':
        return [Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts',
                Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Microsoft/Windows/Fonts']
    if sys.platform == 'darwin':
        return [Path('/System/Library/Fonts'), Path('/Library/Fonts'), Path.home() / 'Library/Fonts']
    return [Path('/usr/share/fonts'), Path('/usr/local/share/fonts'),
            Path.home() / '.local/share/fonts', Path.home() / '.fonts']


def names(data):
    records = {}
    for i in range(u16(data, 2)):
        platform, encoding, language, name_id, length, offset = struct.unpack_from('>6H', data, 6 + i * 12)
        if name_id not in (1, 2, 16, 17):
            continue
        start = u16(data, 4) + offset
        raw = data[start:start + length]
        try:
            if platform in (0, 3):
                value = raw.decode('utf-16-be')
            elif platform == 1 and encoding == 0:
                value = raw.decode('mac_roman')
            else:
                continue
        except UnicodeError:
            continue
        if value:
            records.setdefault(name_id, []).append((language, value))

    def preferred(ids):
        for name_id in ids:
            if records.get(name_id):
                return next((v for lang, v in records[name_id] if lang == 0x409), records[name_id][0][1])
        return ''

    aliases = sorted({v for key in (1, 16) for _, v in records.get(key, [])})
    return preferred((16, 1)), preferred((17, 2)), aliases


def cmaps(data):
    lookups, seen = [], set()
    for i in range(u16(data, 2)):
        platform, encoding, offset = struct.unpack_from('>HHI', data, 4 + i * 8)
        if not (platform == 0 or platform == 3 and encoding in (1, 10)) or offset in seen:
            continue
        seen.add(offset)
        kind = u16(data, offset)
        if kind in (12, 13):
            groups = [struct.unpack_from('>III', data, offset + 16 + j * 12)
                      for j in range(u32(data, offset + 12))]
            starts = [g[0] for g in groups]

            def lookup(cp, groups=groups, starts=starts, kind=kind):
                index = bisect.bisect_right(starts, cp) - 1
                if index < 0 or cp > groups[index][1]:
                    return 0
                return groups[index][2] + (cp - groups[index][0] if kind == 12 else 0)

            lookups.append(lookup)
        elif kind == 4:
            count = u16(data, offset + 6) // 2
            ends_at = offset + 14
            starts_at = ends_at + count * 2 + 2
            deltas_at = starts_at + count * 2
            ranges_at = deltas_at + count * 2
            ends = [u16(data, ends_at + j * 2) for j in range(count)]

            def lookup(cp, ends=ends, starts_at=starts_at, deltas_at=deltas_at, ranges_at=ranges_at):
                if cp > 0xFFFF:
                    return 0
                index = bisect.bisect_left(ends, cp)
                if index == len(ends) or cp < u16(data, starts_at + index * 2):
                    return 0
                delta = u16(data, deltas_at + index * 2)
                range_offset = u16(data, ranges_at + index * 2)
                if not range_offset:
                    return (cp + delta) & 0xFFFF
                glyph = u16(data, ranges_at + index * 2 + range_offset + 2 * (cp - u16(data, starts_at + index * 2)))
                return (glyph + delta) & 0xFFFF if glyph else 0

            lookups.append(lookup)
    return lookups


def inspect(path, requested):
    data = path.read_bytes()
    offsets = [u32(data, 12 + i * 4) for i in range(u32(data, 8))] if data[:4] == b'ttcf' else [0]
    for face_index, offset in enumerate(offsets):
        tables = {}
        for i in range(u16(data, offset + 4)):
            tag, _, start, length = struct.unpack_from('>4sIII', data, offset + 12 + i * 16)
            if start + length > len(data):
                raise ValueError('Font table extends beyond file')
            tables[tag] = data[start:start + length]
        family, style, aliases = names(tables[b'name'])
        lookups = cmaps(tables[b'cmap'])
        if not lookups:
            raise ValueError('No supported Unicode cmap (4/12/13)')
        present = lambda cp: any(lookup(cp) != 0 for lookup in lookups)
        hangul_count = sum(present(cp) for cp in range(0xAC00, 0xD7A4))
        if not hangul_count:
            continue
        missing = ''.join(chr(cp) for cp in sorted(requested) if not present(cp))
        os2 = tables.get(b'OS/2', b'')
        yield {'path': str(path.resolve()), 'face_index': face_index,
               'family': family, 'style': style, 'family_aliases': aliases,
               'weight_class': u16(os2, 4) if len(os2) >= 6 else None,
               'width_class': u16(os2, 6) if len(os2) >= 8 else None,
               'panose': list(os2[32:42]) if len(os2) >= 42 else None,
               'variable': b'fvar' in tables, 'hangul_syllables': hangul_count,
               'hangul_total': 11172, 'covers_requested_text': not missing,
               'missing_characters': missing}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font-dir', action='append', type=Path, default=[], help='Additional folder; repeatable.')
    parser.add_argument('--text', default='', help='Text for glyph coverage check.')
    parser.add_argument('--translations', type=Path, help='Check all targets in translations.json.')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    text = args.text
    if args.translations:
        document = json.loads(args.translations.read_text(encoding='utf-8-sig'))
        text += ''.join(entry.get('target', '') for entry in document['entries'])
    requested = {ord(char) for char in text if not char.isspace()}
    paths, warnings = set(), []
    for directory in default_dirs() + args.font_dir:
        if not directory.is_dir():
            if directory in args.font_dir:
                warnings.append({'path': str(directory), 'error': 'Font directory does not exist'})
            continue
        for path in directory.rglob('*'):
            if path.suffix.lower() in ('.ttf', '.otf', '.ttc', '.otc') and path.is_file():
                paths.add(path.resolve())
    fonts = []
    for path in sorted(paths):
        try:
            fonts.extend(inspect(path, requested))
        except (OSError, ValueError, KeyError, IndexError, struct.error) as exc:
            warnings.append({'path': str(path), 'error': str(exc)})
    result = {'schema': 'chipdf-font-inventory/1',
              'checked_characters': ''.join(chr(cp) for cp in sorted(requested)),
              'fonts': fonts, 'warnings': warnings,
              'note': 'Coverage is not visual similarity. Verify rendered previews; TTC face selection and variable axes are renderer dependent.'}
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + '\n', encoding='utf-8')
    else:
        print(serialized)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
