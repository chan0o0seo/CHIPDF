"""Build a native macOS app and ZIP on a Mac of the target architecture."""
from pathlib import Path
import argparse
import datetime
import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / '.deps'), str(ROOT)]

from studio import __version__


def main():
    parser = argparse.ArgumentParser(description='치pdf macOS 앱 빌드')
    parser.add_argument('--with-inpaint', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('macOS용 앱은 macOS에서 빌드해야 합니다.')
    arch = platform.machine()
    if arch not in ('arm64', 'x86_64'):
        parser.error('Apple Silicon 또는 Intel Mac에서 실행해 주세요.')
    import PyInstaller.__main__

    ocr = ROOT / 'vendor/tessdata'
    for name in ('jpn.traineddata', 'jpn_vert.traineddata'):
        if not (ocr / name).is_file():
            parser.error('python prepare_assets.py로 OCR 자료를 먼저 준비하세요.')
    model = None
    if args.with_inpaint:
        from prepare_inpaint import verify_model
        model_path = ROOT / 'vendor/models/inpaint/lama_fp32.onnx'
        model = verify_model(model_path)
        import onnxruntime

    build_id = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
    work = ROOT / '.build' / ('macos-' + build_id)
    dist = ROOT / 'dist' / ('macos-' + build_id)
    work.mkdir(parents=True)
    resources = work / 'resources'
    resources.mkdir()
    shutil.copy2(ROOT / 'README.md', resources / 'README.ko.md')
    shutil.copy2(ROOT / 'THIRD_PARTY.md', resources / 'THIRD_PARTY.md')
    shutil.copytree(ROOT / 'docs', resources / 'docs')
    licenses = resources / 'licenses'
    shutil.copytree(ROOT / 'vendor/notices', licenses / 'models-and-native')
    # Include licenses from the active venv as well as project-local dependencies.
    for distribution in importlib.metadata.distributions():
        for entry in distribution.files or []:
            if '.dist-info/' not in str(entry) or not any(
                    word in entry.name.lower() for word in ('license', 'copying', 'notice')):
                continue
            source = Path(distribution.locate_file(entry))
            if source.is_file():
                target = licenses / 'python-packages' / str(entry)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.is_file():
        shutil.copy2(python_license, licenses / 'Python-LICENSE.txt')
    metadata = {'version': __version__, 'build_id': build_id, 'platform': 'macos',
                'architecture': arch, 'minimum_macos': '15.0',
                'signing': 'ad-hoc; not notarized', 'inpaint_model': model}
    (resources / 'release.json').write_text(json.dumps(metadata, indent=2), 'utf-8')
    packages = ['tesserocr', 'ctranslate2', 'sentencepiece', 'pypdfium2',
                'pypdfium2_raw', 'reportlab', 'charset_normalizer']
    data = [(str(ROOT / 'assets'), 'assets'), (str(ocr), 'ocr-models'),
            (str(resources), 'release-info')]
    if model:
        data.append((str(model_path), 'vendor/models/inpaint'))
    excluded = ['PySide6.QtWebEngineCore', 'PySide6.QtQml', 'PySide6.QtQuick',
                'PySide6.QtTest', 'torch', 'transformers', 'tensorflow',
                'cryptography', 'Crypto', 'Cryptodome']
    if not model:
        excluded.append('onnxruntime')
    info = {'CFBundleDisplayName': '치pdf', 'CFBundleShortVersionString': __version__,
            'CFBundleVersion': __version__, 'LSMinimumSystemVersion': '15.0',
            'NSHighResolutionCapable': True,
            'CFBundleDocumentTypes': [{'CFBundleTypeName': 'ChiPDF Project',
                'CFBundleTypeExtensions': ['twproj'], 'CFBundleTypeRole': 'Editor',
                'LSHandlerRank': 'Alternate'}]}
    spec = work / 'ChiPDF.spec'
    spec.write_text(f'''
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs
datas = {data!r}
binaries = []
hiddenimports = []
for package in {packages!r}:
    extra_data, extra_binaries, extra_imports = collect_all(package)
    datas += extra_data
    binaries += extra_binaries
    hiddenimports += extra_imports
if {bool(model)!r}:
    hiddenimports.append('onnxruntime')
    binaries += collect_dynamic_libs('onnxruntime')
a = Analysis([{str(ROOT / 'main.py')!r}], pathex={[str(ROOT), str(ROOT / '.deps')]!r},
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes={excluded!r})
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ChiPDF',
          console=False, argv_emulation=False, target_arch={arch!r},
          codesign_identity=None, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name='ChiPDF', upx=False)
app = BUNDLE(coll, name='ChiPDF.app', icon={str(ROOT / 'assets/chipdf.png')!r},
             bundle_identifier='com.chan0o0seo.chipdf', info_plist={info!r})
''', 'utf-8')
    PyInstaller.__main__.run(['--noconfirm', '--distpath', str(dist),
                             '--workpath', str(work / 'work'), str(spec)])
    app = dist / 'ChiPDF.app'
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    edition = '-LaMa' if model else ''
    archive = dist / f'ChiPDF-{__version__}-macOS-{arch}{edition}.zip'
    # ditto preserves bundle symlinks and executable permissions; shutil ZIP does not.
    subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(app), str(archive)], check=True)
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    checksums = dist / 'SHA256SUMS.txt'
    checksums.write_text(f'{digest}  {archive.name}\n', 'utf-8')
    metadata.update(app=str(app), exe=str(app / 'Contents/MacOS/ChiPDF'),
                    zip=str(archive), sha256=digest, checksums=str(checksums))
    (ROOT / 'latest-macos-build.json').write_text(json.dumps(metadata, indent=2), 'utf-8')
    print(json.dumps(metadata), flush=True)


if __name__ == '__main__':
    main()
