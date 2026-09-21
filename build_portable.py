"""Build an independent windowed Windows app, with no adjacent legacy dependency."""
from pathlib import Path
import argparse
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
import importlib
import json
import shutil
import uuid
import PyInstaller.__main__
from studio import APP_NAME, __version__
from studio.translation_config import MODEL_DIRECTORY, MODEL_FILES, MODEL_ID, MODEL_REVISION

parser = argparse.ArgumentParser(description="치pdf 경량 이동식 배포본 생성")
parser.add_argument("--with-offline-model", action="store_true", help="기존 방식으로 오프라인 모델도 포함")
parser.add_argument("--with-inpaint", action="store_true", help="LaMa 사진 복원 모델과 ONNX CPU 런타임 포함")
args = parser.parse_args()
model_dir = ROOT / "vendor" / MODEL_DIRECTORY
model_origin = None
model_options = []
if args.with_offline_model:
    model_origin = json.loads((model_dir / "origin.json").read_text("utf-8"))
    if (model_origin.get("model"), model_origin.get("revision"), model_origin.get("quantization")) != (MODEL_ID, MODEL_REVISION, "int8"):
        raise ValueError("Prepare the pinned translation model before building.")
    if not all((model_dir / name).is_file() and (model_dir / name).stat().st_size for name in MODEL_FILES):
        raise ValueError("The translation model is incomplete. Run prepare_m2m.py first.")
    model_options = ["--add-data", str(model_dir) + ";vendor/" + MODEL_DIRECTORY]

inpaint_metadata = None
inpaint_options = ["--exclude-module", "onnxruntime"]
if args.with_inpaint:
    from prepare_inpaint import verify_model

    inpaint_model = ROOT / "vendor" / "models" / "inpaint" / "lama_fp32.onnx"
    if not inpaint_model.is_file() or not inpaint_model.stat().st_size:
        raise ValueError("LaMa model is missing. Run prepare_inpaint.py before building with --with-inpaint.")
    inpaint_origin_data = verify_model(inpaint_model)
    try:
        inpaint_runtime = importlib.import_module("onnxruntime")
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "ONNX Runtime is unavailable. Install requirements-inpaint.txt into .deps with "
            "python -m pip install --target .deps -r requirements-inpaint.txt, then rebuild."
        ) from exc
    # Include inference and its provider DLLs without model-export/benchmark tools.
    # collect-all pulls optional pandas/scipy tooling from the developer runtime.
    inpaint_options = ["--hidden-import", "onnxruntime", "--collect-binaries", "onnxruntime",
                       "--add-data", str(inpaint_model) + ";vendor/models/inpaint"]
    inpaint_metadata = {
        "engine": "lama", "runtime": "onnxruntime", "runtime_version": inpaint_runtime.__version__,
        "model": "vendor/models/inpaint/lama_fp32.onnx", "sha256": inpaint_origin_data["sha256"],
        "bytes": inpaint_model.stat().st_size, "origin": inpaint_origin_data,
    }
    inpaint_origin = inpaint_model.parent / "origin.json"
    if inpaint_origin.is_file():
        inpaint_options.extend(["--add-data", str(inpaint_origin) + ";vendor/models/inpaint"])

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
    *model_options,
    *inpaint_options,
    "--add-data", str(ROOT / 'assets') + ';assets',
    str(ROOT / "main.py"),
])
app_dir = dist / "Translation Studio"
shutil.copy2(ROOT / "README.md", app_dir / "README.ko.md")
shutil.copy2(ROOT / "THIRD_PARTY.md", app_dir / "THIRD_PARTY.md")
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
    'edition': 'offline-bundled' if args.with_offline_model else 'light',
    'default_translation_engine': 'chrome',
    'translation_model': model_origin,
    'inpaint_model': inpaint_metadata,
    'exe_sha256': hashlib.sha256((app_dir / 'Translation Studio.exe').read_bytes()).hexdigest(),
}, indent=2), 'utf-8')
archive_name = "Translation-Studio-Windows" if args.with_offline_model else "ChiPDF-Windows-Light"
if args.with_inpaint:
    archive_name += "-LaMa"
archive = shutil.make_archive(str(dist / archive_name), "zip", dist, "Translation Studio")
size_bytes = sum(path.stat().st_size for path in app_dir.rglob('*') if path.is_file())
(ROOT / "latest-build.json").write_text(json.dumps({"id": build_id, "version": __version__,
    "edition": "offline-bundled" if args.with_offline_model else "light",
    "inpaint_model": inpaint_metadata,
    "exe": str(app_dir / "Translation Studio.exe"), "zip": archive,
    "unpacked_bytes": size_bytes, "zip_bytes": Path(archive).stat().st_size}, indent=2), "utf-8")
print("BUILD_RESULT=" + json.dumps(str(app_dir / "Translation Studio.exe"), ensure_ascii=True))
print("BUILD_SIZE=" + json.dumps({"unpacked_bytes": size_bytes, "zip_bytes": Path(archive).stat().st_size}))
