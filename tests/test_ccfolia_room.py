"""CCFOLIA room rebuild: translated strings, hash-named images, references and token."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/chipdf-ja-ko/scripts/ccfolia_room.py'
PNG = b'\x89PNG\r\n\x1a\n' + b'original'


def sha(data):
    return hashlib.sha256(data).hexdigest()


class CcfoliaRoomTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'qa', prefix='room-')
        self.work = Path(self.temp.name)
        self.image = sha(PNG) + '.png'
        scene = {'name': 'ゲーム画面', 'backgroundUrl': self.image, 'text': 'ようこそ'}
        self.document = {
            'meta': {'version': '1.1.0'},
            'entities': {'room': {'backgroundUrl': self.image}, 'items': {
                'button': {'memo': '押してね', 'imageUrl': self.image, 'clickAction': {'text': '/scene ゲーム画面'}}},
                'decks': {}, 'notes': {}, 'characters': {}, 'effects': {},
                'scenes': {'s1': scene}, 'savedatas': {}, 'snapshots': {'p1': {'scenes': {'s1': dict(scene)}}}},
            'resources': {self.image: {'type': 'image/png'}}}
        self.room = self.work / 'ルームデータ.zip'
        data = json.dumps(self.document, ensure_ascii=False, separators=(',', ':')).encode()
        with zipfile.ZipFile(self.room, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(self.image, PNG)
            archive.writestr('__data.json', data)
            archive.writestr('.token', '0.' + sha(data))
        self.original = self.room.read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True, encoding='utf-8')

    def table(self, **targets):
        (self.work / 'tr.json').unlink(missing_ok=True)
        result = self.run_script('inspect', self.room, '--output', self.work / 'inv.json', '--template', self.work / 'tr.json')
        self.assertEqual(result.returncode, 0, result.stderr)
        table = json.loads((self.work / 'tr.json').read_text(encoding='utf-8'))
        for entry in table['entries']:
            target = targets.get(entry['path'].rsplit('/', 1)[-1])
            entry.update(decision='translate', target=target) if target else entry.update(decision='preserve')
        (self.work / 'tr.json').write_text(json.dumps(table, ensure_ascii=False), encoding='utf-8')
        return table

    def build(self, *extra):
        return self.run_script('build', self.room, '--translations', self.work / 'tr.json', '--output',
                               self.work / 'ko' / self.room.name, '--report', self.work / 'build.json', *extra)

    def test_template_lists_japanese_strings_but_not_references(self):
        paths = {entry['path'] for entry in self.table()['entries']}
        self.assertIn('/entities/items/button/clickAction/text', paths)
        self.assertIn('/entities/snapshots/p1/scenes/s1/name', paths)
        self.assertFalse(any(path.endswith('Url') for path in paths))

    def test_build_translates_renames_images_and_keeps_the_original(self):
        self.table(name='게임 화면', text='/scene 게임 화면', memo='눌러 줘')
        table = json.loads((self.work / 'tr.json').read_text(encoding='utf-8'))
        for entry in table['entries']:
            if entry['path'].endswith('/s1/text'):
                entry.update(decision='translate', target='어서 오세요')
        (self.work / 'tr.json').write_text(json.dumps(table, ensure_ascii=False), encoding='utf-8')
        translated = b'\x89PNG\r\n\x1a\n' + '한국어'.encode()
        (self.work / 'ko.png').write_bytes(translated)
        (self.work / 'assets.json').write_text(json.dumps({'replacements': [{'name': self.image, 'file': 'ko.png'}]}))
        result = self.build('--assets', self.work / 'assets.json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.room.read_bytes(), self.original)
        output = self.work / 'ko' / self.room.name
        with zipfile.ZipFile(output) as archive:
            data = archive.read('__data.json')
            self.assertEqual(archive.read('.token').decode(), '0.' + sha(data))
            new = sha(translated) + '.png'
            self.assertEqual(sorted(archive.namelist()), sorted(['.token', '__data.json', new]))
            self.assertEqual(archive.read(new), translated)
        document = json.loads(data)
        self.assertEqual(document['resources'], {new: {'type': 'image/png'}})
        button = document['entities']['items']['button']
        self.assertEqual((button['imageUrl'], button['clickAction']['text'], button['memo']), (new, '/scene 게임 화면', '눌러 줘'))
        self.assertEqual(document['entities']['snapshots']['p1']['scenes']['s1']['backgroundUrl'], new)
        report = json.loads((self.work / 'build.json').read_text(encoding='utf-8'))
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['japanese_strings_remaining'], [])
        self.assertFalse(report['actual_ccfolia_import_tested'])
        validated = self.run_script('validate', output, '--original', self.room, '--output', self.work / 'val.json')
        self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)

    def test_build_refuses_unsafe_or_incomplete_results(self):
        # A renamed scene whose /scene command still uses the old name would break the button.
        self.table(name='게임 화면', memo='눌러 줘')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('/scene', result.stderr)
        # Rows left undecided block the build unless a draft is requested.
        table = self.table(name='게임 화면', text='/scene 게임 화면')
        table['entries'][0]['decision'] = ''
        (self.work / 'tr.json').write_text(json.dumps(table, ensure_ascii=False), encoding='utf-8')
        self.assertIn('undecided', self.build().stderr)
        self.assertEqual(self.build('--allow-incomplete').returncode, 0)
        # A JPEG saved under a .png resource name is refused.
        (self.work / 'bad.png').write_bytes(b'\xff\xd8\xff\xe0jpeg')
        (self.work / 'assets.json').write_text(json.dumps({'replacements': [{'name': self.image, 'file': 'bad.png'}]}))
        result = self.build('--assets', self.work / 'assets.json', '--allow-incomplete', '--overwrite')
        self.assertIn('original format', result.stderr)
        # Text edited after inspection is not overwritten blindly.
        table['entries'][0]['source_sha256'] = '0' * 64
        (self.work / 'tr.json').write_text(json.dumps(table, ensure_ascii=False), encoding='utf-8')
        self.assertIn('differs', self.build('--overwrite').stderr)


if __name__ == '__main__':
    unittest.main()
