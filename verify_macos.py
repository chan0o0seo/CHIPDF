"""Run the built app from a Unicode path with development library paths removed."""
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    if sys.platform != 'darwin':
        raise SystemExit('Run packaged macOS verification on macOS.')
    metadata = json.loads((ROOT / 'latest-macos-build.json').read_text('utf-8'))
    output = ROOT / 'qa/macos'
    output.mkdir(parents=True, exist_ok=True)
    app = output / '한글 앱/ChiPDF.app'
    if app.exists():
        raise SystemExit('Use a fresh qa/macos directory for each verification.')
    app.parent.mkdir(parents=True)
    shutil.copytree(metadata['app'], app, symlinks=True)
    with (app / 'Contents/Info.plist').open('rb') as stream:
        info = plistlib.load(stream)
    assert info['CFBundleShortVersionString'] == metadata['version']
    assert info['LSMinimumSystemVersion'] == '15.0'
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    exe = app / 'Contents/MacOS/ChiPDF'
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('PYTHON', 'DYLD_', 'QT_'))}
    env['PATH'] = '/usr/bin:/bin:/usr/sbin:/sbin'
    env['CHIPDF_LAMA_MODEL'] = ''
    data = output / '사용자 데이터'
    for name, extra in [('open', [str(ROOT / 'assets/chipdf.png'), '--smoke-native', '--smoke-collection']),
                        ('welcome', [])]:
        target = output / name
        subprocess.run([str(exe), *extra, '--data-dir', str(data), '--smoke-dir', str(target)],
                       cwd=output, env=env, check=True, timeout=180)
        assert (target / 'ok.txt').is_file(), f'{name} did not complete'
        state = json.loads((target / 'smoke-state.json').read_text('utf-8'))
        assert state['version'] == metadata['version']
    native = json.loads((output / 'open/native-smoke.json').read_text('utf-8'))
    assert native['architecture'] == metadata['architecture'] == platform.machine()
    assert native['ocr_languages'] == ['jpn', 'jpn_vert']
    assert native['lama_inference'] and native['unselected_pixels_preserved']
    assert (output / 'open/output.pdf').is_file()
    recent = json.loads((data / 'recent.json').read_text('utf-8'))
    assert Path(recent[0]['path']) == output / 'open/output.twproj'
    archive = Path(metadata['zip'])
    with archive.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == metadata['sha256']
    (output / 'result.json').write_text(json.dumps({**native, 'version': metadata['version'],
        'unicode_bundle_path': True, 'pdf_export': True, 'recent_work': True,
        'ad_hoc_signature_verified': True}, indent=2), 'utf-8')
    print((output / 'result.json').read_text('utf-8'))


if __name__ == '__main__':
    main()
