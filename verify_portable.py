"""Relocate the built ZIP and verify its own Python/Qt runtime can open and export."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import uuid
import zipfile

ROOT = Path(__file__).resolve().parent
info = json.loads((ROOT / "latest-build.json").read_text("utf-8"))
probe = ROOT / "qa" / ("portable-" + uuid.uuid4().hex[:8])
probe.mkdir(parents=True)
with zipfile.ZipFile(info["zip"]) as archive:
    names = archive.namelist()
    assert not any("/torch/" in name or "/transformers/" in name or name.endswith(".twproj") for name in names), "Development dependencies or user projects leaked into archive"
    archive.extractall(probe)
exe = probe / "Translation Studio" / "Translation Studio.exe"
output = probe / "result"
env = os.environ.copy()
for key in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QT_QPA_PLATFORM"):
    env.pop(key, None)
system_root = os.environ["SystemRoot"]
env["PATH"] = str(Path(system_root) / "System32") + os.pathsep + system_root
def run(file, output, workflow=False, collection=False):
    args = [str(exe), str(file), "--data-dir", str(probe / "data"), "--smoke-dir", str(output)]
    if workflow:
        args.append("--smoke-workflow")
    if collection:
        args.append('--smoke-collection')
    result = subprocess.run(args, cwd=probe, env=env, timeout=240 if collection else 150 if workflow else 30,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    logs = "\n".join(path.read_text("utf-8") for path in output.glob("*.log"))
    assert result.returncode == 0, f"Packaged app failed: {result.returncode}\n{logs}"
    assert (output / "ok.txt").exists(), "Packaged app did not finish smoke check: " + logs

# Build a genuine v1-schema fixture from the retained original edit values;
# older QA runs had autosaved that fixture using a later manifest version.
v1_project = probe / "previous-version-1.twproj"
with zipfile.ZipFile(ROOT / "qa" / "real-card" / "편집시험.twproj") as archive:
    v1_data = json.loads(archive.read("manifest.json"))
    v1_original = archive.read("assets/original.png")
v1_data["version"] = 1
v1_data["pages"][0].pop("ocr_done", None)
v1_keys = {"id", "x", "y", "width", "height", "rotation", "z", "fill", "paragraphs", "source_text", "source_rect", "erase_rect"}
for obj in v1_data["pages"][0]["objects"]:
    for key in list(obj):
        if key not in v1_keys:
            del obj[key]
    for paragraph in obj["paragraphs"]:
        for key in ("line_spacing", "space_before", "space_after"):
            paragraph.pop(key, None)
        for run_data in paragraph["runs"]:
            run_data["style"].pop("strike", None)
with zipfile.ZipFile(v1_project, "w") as archive:
    archive.writestr("manifest.json", json.dumps(v1_data, ensure_ascii=False))
    archive.writestr("assets/original.png", v1_original)
v1_before = v1_project.read_bytes()
run(v1_project, output)
assert v1_project.read_bytes() == v1_before
assert (output / "output.png").read_bytes() == (ROOT / "qa" / "real-card" / "편집시험.png").read_bytes(), "Version 1 render differs"
v2_output = probe / "version-2"
v2_project = ROOT / "qa" / "workflow-02" / "직접수정.twproj"
v2_before = v2_project.read_bytes()
run(v2_project, v2_output)
assert v2_project.read_bytes() == v2_before
assert (v2_output / "output.png").read_bytes() == (ROOT / "qa" / "workflow-02" / "직접수정.png").read_bytes(), "Version 2 render differs"
v3_output = probe / "version-3"
v3_project = ROOT / "qa" / "editing-03" / "편집예시.twproj"
v3_before = v3_project.read_bytes()
run(v3_project, v3_output)
assert (v3_output / "output.png").read_bytes() == (ROOT / "qa" / "editing-03" / "편집예시.png").read_bytes(), "Mixed object render differs"
assert v3_project.read_bytes() == v3_before, "Opening a project unexpectedly rewrote it"
v4_output = probe / "version-4"
v4_project = ROOT / "qa" / "layout-04" / "그룹편집.twproj"
v4_before = v4_project.read_bytes()
run(v4_project, v4_output)
assert (v4_output / "output.png").read_bytes() == (ROOT / "qa" / "layout-04" / "그룹편집.png").read_bytes(), "Nested groups and paragraph layout differ"
assert v4_project.read_bytes() == v4_before, "Opening a v4 project unexpectedly rewrote it"
v5_output = probe / 'version-5'
v5_project = ROOT / 'qa' / 'collection-05' / '작품.twproj'
v5_before = v5_project.read_bytes()
run(v5_project, v5_output, collection=True)
v5_report = json.loads((ROOT / 'qa' / 'collection-05' / 'result.json').read_text('utf-8'))
outputs = sorted((v5_output / 'pages').glob('*.png'))
assert len(outputs) == 27
assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in outputs] == v5_report['page_png_sha256']
assert v5_project.read_bytes() == v5_before
from pypdf import PdfReader
pdf = PdfReader(v5_output / 'output.pdf')
assert len(pdf.pages) == 27
for page, (width, height) in zip(pdf.pages, v5_report['physical_sizes']):
    assert abs(float(page.mediabox.width)-width) < .01 and abs(float(page.mediabox.height)-height) < .01
v6_output = probe / 'version-6'
v6_project = ROOT / 'qa' / 'vertical-06' / '작업.twproj'
v6_report = json.loads((ROOT / 'qa' / 'vertical-06' / 'result.json').read_text('utf-8'))
assert v6_report['version'] == 6 and v6_report['pages'] == 3
v6_before = v6_project.read_bytes()
run(v6_project, v6_output, collection=True)
v6_pngs = sorted((v6_output / 'pages').glob('*.png'))
assert len(v6_pngs) == v6_report['pages']
assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in v6_pngs] == v6_report['page_png_sha256'], 'Vertical/mixed text or transformed group render differs'
assert v6_project.read_bytes() == v6_before, 'Opening a v6 project unexpectedly rewrote it'
v6_pdf = PdfReader(v6_output / 'output.pdf')
assert len(v6_pdf.pages) == v6_report['pages']
for page, (width, height) in zip(v6_pdf.pages, v6_report['physical_sizes']):
    assert abs(float(page.mediabox.width)-width) < .01 and abs(float(page.mediabox.height)-height) < .01
with zipfile.ZipFile(v6_output / 'output.twproj') as archive:
    v6_saved = json.loads(archive.read('manifest.json'))
assert v6_saved['version'] == 8
assert sum(obj.get('writing_mode') == 'vertical-rl' for page in v6_saved['pages'] for obj in page['objects']) == 3
pdf_input = probe / 'PDF자료.pdf'
shutil.copy2(ROOT / 'qa' / 'collection-05' / 'native-input.pdf', pdf_input)
pdf_before = pdf_input.read_bytes()
pdf_output = probe / 'pdf-import'
run(pdf_input, pdf_output, collection=True)
assert pdf_input.read_bytes() == pdf_before
assert len(PdfReader(pdf_output / 'output.pdf').pages) == 6
assert len(list((pdf_output / 'pages').glob('*.png'))) == 6
pdf_state = json.loads((pdf_output / 'smoke-state.json').read_text('utf-8'))
assert pdf_state['auto_ocr'] is False and pdf_state['canvas_tool'] == 'ocr'
with zipfile.ZipFile(pdf_output / 'output.twproj') as archive:
    pdf_manifest = json.loads(archive.read('manifest.json'))
assert all(not page['objects'] and not page['ocr_done'] for page in pdf_manifest['pages']), 'PDF opening must not automatically recognize paragraphs'

# Exercise schema 7 through the relocated app's own Qt/Pillow runtime.
manual_report = json.loads((ROOT / 'qa' / 'manual-08' / 'result.json').read_text('utf-8'))
assert manual_report['passed'] and manual_report['project_version'] in (7, 8)
manual_project = ROOT / manual_report['project']
manual_before = manual_project.read_bytes()
manual_output = probe / 'manual-08'
run(manual_project, manual_output, collection=True)
assert manual_project.read_bytes() == manual_before
assert hashlib.sha256((manual_output / 'output.png').read_bytes()).hexdigest() == manual_report['png_sha256'], 'Manual OCR/brush restoration render differs in packaged app'
with zipfile.ZipFile(manual_output / 'output.twproj') as archive:
    manual_manifest = json.loads(archive.read('manifest.json'))
    assert {key: hashlib.sha256(archive.read(key)).hexdigest() for key in manual_report['original_assets']} == manual_report['original_assets']
assert manual_manifest['version'] == 8 and len(manual_manifest['pages'][0]['background_patches']) == 1
assert manual_manifest['pages'][0]['objects'][0]['erase_when_empty'] is True
manual_pdf = PdfReader(manual_output / 'output.pdf')
assert len(manual_pdf.pages) == 1
assert [float(manual_pdf.pages[0].mediabox.width), float(manual_pdf.pages[0].mediabox.height)] == manual_report['pdf_size_pt']
from PIL import Image
with Image.open(manual_output / 'output.png') as manual_png:
    assert manual_pdf.pages[0].images[0].image.convert('RGB').tobytes() == manual_png.convert('RGB').tobytes(), 'Packaged PDF/PNG pixels differ'
manual_reopened = probe / 'manual-08-reopened'
run(manual_output / 'output.twproj', manual_reopened)
assert (manual_reopened / 'output.png').read_bytes() == (manual_output / 'output.png').read_bytes()

native_report = json.loads((ROOT / 'qa/pdf-background-081/result.json').read_text('utf-8'))
assert native_report['passed'] and all(p['legacy_identical'] for p in native_report['native_comparison']['pages'])
native_project = ROOT / native_report['project']
native_before = native_project.read_bytes()
native_output = probe / 'native-pdf-background'
run(native_project, native_output, collection=True)
assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((native_output / 'pages').glob('*.png'))] == native_report['png_hashes']
assert native_project.read_bytes() == native_before
with zipfile.ZipFile(native_output / 'output.twproj') as archive:
    native_manifest = json.loads(archive.read('manifest.json'))
    assert native_manifest['version'] == 8 and all(p['clean_asset'] for p in native_manifest['pages'])
    assert {key: hashlib.sha256(archive.read(key)).hexdigest() for key in native_report['original_assets']} == native_report['original_assets']
# Import native and clipping-text PDFs inside the packaged app as well, so the
# new pypdf runtime and PDFium APIs are exercised rather than only saved patches.
native_import = probe / 'native-pdf-import'
run(ROOT / native_report['native_comparison']['input'], native_import, collection=True)
with zipfile.ZipFile(native_import / 'output.twproj') as archive:
    imported_native = json.loads(archive.read('manifest.json'))
    assert imported_native['version'] == 8 and all(p['clean_asset'] for p in imported_native['pages'])
    for index, page in enumerate(imported_native['pages'], 1):
        clean = Image.open(__import__('io').BytesIO(archive.read(page['clean_asset']))).convert('RGBA')
        expected = Image.open(ROOT / native_report['native_comparison']['run'] / f'{index}-legacy.png').convert('RGBA')
        assert clean.tobytes() == expected.tobytes(), 'Packaged native PDF background differs from previous clean replacement'
assert list((exe.parent / 'licenses').rglob('pypdf-6.10.0.dist-info/licenses/LICENSE')), 'pypdf license missing'
assert list((exe.parent / 'licenses').rglob('pdfium.txt')), 'PDFium third-party notices missing'
sample = probe / "카드.png"
shutil.copy2(ROOT / "qa" / "workflow-02" / "sample.png", sample)
before = hashlib.sha256(sample.read_bytes()).hexdigest()
workflow_output = probe / "workflow"
run(sample, workflow_output, workflow=True)
workflow = json.loads((workflow_output / "workflow.json").read_text("utf-8"))
assert workflow["regions"] == 4 and workflow["erase_patches"] == 4
assert all(text.strip() for text in workflow["targets"])
assert hashlib.sha256(sample.read_bytes()).hexdigest() == before
assert list((exe.parent / "licenses").rglob("*LICENSE*")), "Runtime license files missing"
report = {"build": info["id"], "exit_code": 0, "relocated_zip": True,
          "system_only_path": True, "native_window_capture": str(output / "window.png"),
          "export_byte_identical": True, "v2_export_byte_identical": True,
          "actual_v1_schema_checked": True,
          "v3_mixed_export_byte_identical": True, "opening_project_does_not_rewrite": True,
          "v4_nested_groups_paragraphs_export_byte_identical": True,
          "v5_collection_png_identical": 27, "v5_pdf_physical_sizes_preserved": True,
          "v6_vertical_collection_png_identical": len(v6_pngs), "v6_pdf_physical_sizes_preserved": True,
          "v6_vertical_mode_roundtrip": True,
          "native_pdf_import_and_output_pages": 6,
          "manual_import_is_default": True, "v7_manual_background_png_identical": True,
          "v7_brush_and_empty_box_roundtrip": True, "v7_pdf_png_pixels_identical": True,
          "v8_native_pdf_background_pages": 4, "v8_native_import_matches_legacy_background": True,
          "v8_self_contained_background_roundtrip": True,
          "packaged_ocr_regions": workflow["regions"], "packaged_translation_drafts": len(workflow["targets"]),
          "original_unchanged": True, "no_developer_models_or_user_projects": True,
          "zip_bytes": Path(info["zip"]).stat().st_size,
          "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest()}
(ROOT / "qa" / "portable-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
print(json.dumps(report, ensure_ascii=True))
