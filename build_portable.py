"""Build an independent windowed Windows app, with no adjacent legacy dependency."""
from pathlib import Path
import os
import sys
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / ".deps"))
# Do not let unrelated developer tools (e.g. Poppler's icuuc.dll) satisfy Qt DLLs.
# Qt on supported Windows 10/11 uses the operating system's ICU API. The Poppler variant has
# different exports despite sharing its filename.
system_root = Path(os.environ["SystemRoot"])
os.environ["PATH"] = os.pathsep.join(map(str, [ROOT / ".deps" / "PySide6", ROOT / ".deps" / "shiboken6",
                                             system_root / "System32", system_root]))
import datetime
import hashlib
import json
import shutil
import uuid
import PyInstaller.__main__
from studio import APP_NAME, __version__

build_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
dist = ROOT / "dist" / build_id
work = ROOT / ".build" / build_id
work.mkdir(parents=True, exist_ok=True)
version_info = work / 'windows-version.txt'
version_tuple = tuple(map(int, __version__.split('.'))) + (0,)
version_info.write_text(f'''VSVersionInfo(
    ffi=FixedFileInfo(filevers={version_tuple!r}, prodvers={version_tuple!r},
        mask=0x3f, flags=0, OS=0x40004, fileType=0x1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable('041204B0', [
        StringStruct('FileDescription', {APP_NAME!r}),
        StringStruct('ProductName', {APP_NAME!r}),
        StringStruct('FileVersion', {__version__!r}),
        StringStruct('ProductVersion', {__version__!r}),
        StringStruct('InternalName', 'ChiPDF'),
        StringStruct('OriginalFilename', 'Translation Studio.exe')
    ])]), VarFileInfo([VarStruct('Translation', [1042, 1200])])]
)''', 'utf-8')
PyInstaller.__main__.run([
    "--noconfirm", "--windowed", "--onedir", "--name", "Translation Studio",
    "--icon", str(ROOT / 'assets' / 'chipdf.ico'), "--version-file", str(version_info),
    "--distpath", str(dist), "--workpath", str(work / "work"), "--specpath", str(work),
    "--paths", str(ROOT), "--paths", str(ROOT / ".deps"),
    "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtQml",
    "--exclude-module", "PySide6.QtQuick", "--exclude-module", "PySide6.QtTest",
    "--exclude-module", "torch", "--exclude-module", "transformers", "--exclude-module", "tensorflow",
    # Password-protected PDFs are not imported; keep optional pypdf crypto
    # providers from pulling unrelated development-environment dependencies.
    "--exclude-module", "cryptography", "--exclude-module", "Crypto", "--exclude-module", "Cryptodome",
    "--collect-all", "tesserocr", "--collect-all", "ctranslate2", "--collect-all", "sentencepiece",
    "--collect-all", "pypdfium2", "--collect-all", "pypdfium2_raw",
    "--collect-all", "reportlab", "--collect-all", "charset_normalizer",
    "--add-data", str(ROOT / "vendor" / "tessdata") + ";ocr-models",
    "--add-data", str(ROOT / "vendor" / "m2m100-int8") + ";vendor/m2m100-int8",
    "--add-data", str(ROOT / 'assets') + ';assets',
    str(ROOT / "main.py"),
])
app_dir = dist / "Translation Studio"
shutil.copy2(ROOT / "README.md", app_dir / "README.ko.md")
for name in ("THIRD_PARTY.md", "PRODUCT_PLAN.ko.md", "IMPLEMENTATION_01.ko.md", "IMPLEMENTATION_02.ko.md", "IMPLEMENTATION_03.ko.md", "IMPLEMENTATION_04.ko.md", "IMPLEMENTATION_05.ko.md", "IMPLEMENTATION_06.ko.md", "IMPLEMENTATION_07.ko.md", "IMPLEMENTATION_08.ko.md", "WINDOWS_COMPATIBILITY.ko.md", "ENGINE_REVIEW.ko.md"):
    shutil.copy2(ROOT / name, app_dir / name)
licenses = app_dir / "licenses"
licenses.mkdir()
shutil.copytree(ROOT / "vendor" / "notices", licenses / "models-and-native")
for package in (ROOT / ".deps").glob("*.dist-info"):
    for path in package.rglob("*"):
        if path.is_file() and any(term in str(path.relative_to(package)).lower() for term in ("license", "copying", "notice")):
            dest = licenses / package.name / path.relative_to(package)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
python_license = Path(sys.base_prefix) / "LICENSE.txt"
for path in (ROOT / '.deps' / 'reportlab' / 'fonts').glob('*'):
    if path.is_file() and any(term in path.name.lower() for term in ('license', 'copying', 'notice', 'copyright')):
        dest = licenses / 'reportlab-support' / path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
if python_license.exists():
    shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
(app_dir / 'release.json').write_text(json.dumps({
    'version': __version__, 'build_id': build_id,
    'exe_sha256': hashlib.sha256((app_dir / 'Translation Studio.exe').read_bytes()).hexdigest(),
}, indent=2), 'utf-8')
archive = shutil.make_archive(str(dist / "Translation-Studio-Windows"), "zip", dist, "Translation Studio")
launcher = '@echo off\r\nstart "" "%~dp0dist\\' + build_id + '\\Translation Studio\\Translation Studio.exe" %*\r\n'
(ROOT / "Start Translation Studio.cmd").write_text(launcher, "ascii", newline="")
(ROOT / "latest-build.json").write_text(json.dumps({"id": build_id, "version": __version__, "exe": str(app_dir / "Translation Studio.exe"), "zip": archive}, indent=2), "utf-8")
print("BUILD_RESULT=" + json.dumps(str(app_dir / "Translation Studio.exe"), ensure_ascii=True))
