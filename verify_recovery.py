"""Verify recovered source and frozen runtimes using newly generated fixtures only.

Run with the restored Python 3.12 environment. All editor data and evidence go
under a fresh qa/recovery-* directory; disposable OCR caches use a private temp
directory. This does not install the app or require any historical QA artifacts.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
import zipfile

ROOT = Path(__file__).resolve().parent
EXPECTED_EXE_SHA256 = "933fe6e176f5f66443f787735f0327a05b049e137a012fe6cc5189f679d33c15"
sys.path.insert(0, str(ROOT / ".deps"))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text("utf-8-sig"))


def pixel_hash(image):
    image = image.convert("RGBA")
    return sha256(f"{image.width}x{image.height}:RGBA:".encode() + image.tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-python", type=Path, default=Path(sys.executable))
    args = parser.parse_args()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    run = ROOT / "qa" / ("recovery-" + run_id)
    run.mkdir(parents=True)
    report = {
        "passed": False, "status": "running", "run": str(run),
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "historical_qa_required": False, "checks": [], "processes": [],
        "runtimes": {}, "fixtures": {},
    }

    def persist():
        data = json.dumps(report, ensure_ascii=False, indent=2)
        (run / "result.json").write_text(data, "utf-8")
        (ROOT / "qa" / "recovery-runtime-result.json").write_text(data, "utf-8")

    def require(condition, label):
        if not condition:
            raise RuntimeError(label)
        report["checks"].append(label)
        persist()
        print("PASS: " + label, flush=True)

    persist()
    try:
        require(os.name == "nt", "native Windows verification host")
        from PIL import Image, ImageDraw, ImageFont
        import pypdfium2 as pdfium
        from pypdf import PdfReader
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen.canvas import Canvas

        info = read_json(ROOT / "latest-build.json")
        exe = Path(info["exe"])
        if not exe.is_absolute():
            exe = ROOT / exe
        exe = exe.resolve()
        require(exe.is_relative_to((ROOT / "dist").resolve()),
                "frozen executable is the recovered workspace distribution")
        require(exe.is_file(), "recovered executable exists")
        report.update({"build_id": info.get("id"), "exe": str(exe),
                       "exe_sha256": sha256(exe.read_bytes()),
                       "source_python": str(args.source_python.resolve())})
        require(report["exe_sha256"] == EXPECTED_EXE_SHA256,
                "frozen executable matches the original recovered SHA-256")
        require(args.source_python.is_file(), "source Python executable exists")

        fixtures = run / "fixtures"
        fixtures.mkdir()
        font_dir = Path(os.environ["WINDIR"]) / "Fonts"
        font_file = next((font_dir / name for name in
                          ("meiryo.ttc", "YuGothR.ttc", "msgothic.ttc")
                          if (font_dir / name).is_file()), None)
        require(font_file is not None, "Japanese fixture font is available")
        japanese = "鍵は机の上にあります。"
        sample = Image.new("RGB", (1200, 360), (243, 235, 215))
        ImageDraw.Draw(sample).text((80, 100), japanese, fill=(24, 24, 24),
                                   font=ImageFont.truetype(str(font_file), 52), anchor="lt")
        sample_path = fixtures / "japanese.png"
        sample.save(sample_path)

        # The reference PDF is drawn independently without text or text-clipped
        # paint. Comparing it with saved clean assets checks the actual import.
        texture = Image.new("RGB", (240, 180))
        texture.putdata([(120 + x // 3, 60 + y // 2, 140 + (x + y) % 71)
                         for y in range(180) for x in range(240)])
        page_kinds = ("native-text", "text-clip-7", "nested-text-clip-4")

        def make_pdf(path, with_text):
            canvas = Canvas(str(path), pagesize=(240, 180), pageCompression=1)
            for index, kind in enumerate(page_kinds):
                canvas.drawImage(ImageReader(texture), 0, 0, 240, 180)
                canvas.setStrokeColorRGB(0, 1, 1)
                canvas.line(0, 60, 240, 60)
                nested = kind.startswith("nested")
                if nested:
                    canvas.beginForm("text-form", 0, 0, 240, 180)
                canvas.saveState()
                canvas.setFillColorRGB(.1, .8, .3)
                canvas.rect(10, 100, 200, 40, fill=1, stroke=0)
                if with_text:
                    canvas.setFillColorRGB(0, 0, 0)
                    text = canvas.beginText(25, 110)
                    text.setFont("Helvetica", 22)
                    text.setTextRenderMode((0, 7, 4)[index])
                    text.textOut("NATIVE TEXT")
                    canvas.drawText(text)
                    if index:
                        canvas.saveState()
                        canvas.setFillColorRGB(.9, .1, .05)
                        canvas.rect(0, 0, 240, 180, fill=1, stroke=0)
                        canvas.restoreState()
                canvas.restoreState()
                if nested:
                    canvas.endForm()
                    canvas.doForm("text-form")
                canvas.setStrokeColorRGB(.9, .9, .1)
                canvas.line(0, 120, 240, 120)
                canvas.showPage()
            canvas.save()

        native_path, reference_path = fixtures / "native-and-clipping.pdf", fixtures / "text-free-reference.pdf"
        make_pdf(native_path, True)
        make_pdf(reference_path, False)
        references = []
        with pdfium.PdfDocument(reference_path) as document:
            for index in range(len(document)):
                with closing(document[index]) as page, closing(page.render(scale=200 / 72)) as bitmap:
                    expected = bitmap.to_pil().convert("RGBA").copy()
                expected.save(fixtures / f"expected-background-{index + 1}.png")
                references.append(pixel_hash(expected))
        fixture_hashes = {str(path): sha256(path.read_bytes())
                          for path in (sample_path, native_path, reference_path)}
        report["fixtures"] = {"sha256": fixture_hashes, "japanese": japanese,
                              "font": str(font_file), "pdf_page_kinds": page_kinds,
                              "expected_clean_pixel_sha256": references}
        persist()

        def png_hash(path):
            with Image.open(path) as image:
                return pixel_hash(image)

        def bundle(path):
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                assets = {name: archive.read(name) for name in archive.namelist()
                          if name != "manifest.json"}
            return manifest, assets

        def collection(output, label):
            pngs = sorted((output / "pages").glob("*.png"))
            manifest, assets = bundle(output / "output.twproj")
            pdf = PdfReader(output / "output.pdf")
            require(manifest["version"] == 8, label + ": saved project schema is 8")
            require(len(pngs) == len(manifest["pages"]) == len(pdf.pages),
                    label + ": all project pages are exported as PNG and PDF")
            for index, (page, png, pdf_page) in enumerate(zip(manifest["pages"], pngs, pdf.pages), 1):
                require(abs(float(pdf_page.mediabox.width) - page["width_pt"]) < .01
                        and abs(float(pdf_page.mediabox.height) - page["height_pt"]) < .01,
                        f"{label}: page {index} physical dimensions survive PDF export")
                images = list(pdf_page.images)
                require(len(images) == 1 and pixel_hash(images[0].image) == png_hash(png),
                        f"{label}: page {index} PDF and PNG have identical pixels")
            return manifest, assets, [png_hash(path) for path in pngs]

        # The OCR engine needs an ASCII temporary path on some Windows hosts.
        # Its model cache is isolated and removed when this verification ends.
        with tempfile.TemporaryDirectory(prefix="TranslationStudio-recovery-") as scratch:
            report["temporary_cache"] = scratch
            env_base = os.environ.copy()
            for key in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
                env_base.pop(key, None)
            system_root = Path(os.environ["SystemRoot"])
            env_base.update({"PATH": os.pathsep.join((str(system_root / "System32"), str(system_root))),
                             "QT_QPA_PLATFORM": "windows", "PYTHONUTF8": "1",
                             "PYTHONDONTWRITEBYTECODE": "1", "TEMP": scratch, "TMP": scratch})
            report["system_only_path"] = env_base["PATH"]

            def smoke(command, runtime_name, input_path, case, *, workflow=False):
                output = run / runtime_name / case
                output.mkdir(parents=True)
                data_dir = output / "data"
                env = env_base.copy()
                for key in ("APPDATA", "LOCALAPPDATA", "XDG_CACHE_HOME"):
                    isolated = output / key.lower()
                    isolated.mkdir()
                    env[key] = str(isolated)
                argv = [*command, str(input_path), "--data-dir", str(data_dir),
                        "--smoke-dir", str(output),
                        "--smoke-workflow" if workflow else "--smoke-collection"]
                before = sha256(input_path.read_bytes())
                record = {"runtime": runtime_name, "case": case, "command": argv,
                          "timeout_seconds": 165 if workflow else 60, "output": str(output)}
                report["processes"].append(record)
                persist()
                print(f"RUN: {runtime_name}/{case}", flush=True)
                started = time.monotonic()
                try:
                    with (output / "process.log").open("wb") as stream:
                        result = subprocess.run(argv, cwd=run, env=env, stdout=stream,
                                                stderr=subprocess.STDOUT,
                                                timeout=record["timeout_seconds"],
                                                creationflags=subprocess.CREATE_NO_WINDOW)
                    record["exit_code"] = result.returncode
                except subprocess.TimeoutExpired as exc:
                    record["timeout"] = True
                    raise TimeoutError(f"{runtime_name}/{case} timed out; see {output}") from exc
                finally:
                    record["elapsed_seconds"] = round(time.monotonic() - started, 3)
                    record["logs"] = {path.name: path.read_text("utf-8", errors="replace")[-12000:]
                                      for path in output.glob("*.log")}
                    persist()
                if result.returncode != 0 or not (output / "ok.txt").is_file():
                    details = "\n".join(f"{name}:\n{text}" for name, text in record["logs"].items() if text)
                    raise RuntimeError(f"{runtime_name}/{case} failed (exit {result.returncode}); "
                                       f"logs: {output}\n{details}")
                require(True, f"{runtime_name}/{case}: application completed")
                require(sha256(input_path.read_bytes()) == before,
                        f"{runtime_name}/{case}: input file remains unchanged")
                state = read_json(output / "smoke-state.json")
                record["state"] = state
                require(state["version"] == "0.8.1" and Path(state["data_dir"]).resolve() == data_dir.resolve(),
                        f"{runtime_name}/{case}: version 0.8.1 uses isolated application data")
                require(state["auto_ocr"] is workflow and not state["presets_load_error"],
                        f"{runtime_name}/{case}: requested OCR mode and clean preset startup")
                with Image.open(output / "window.png") as capture:
                    require(capture.width >= 400 and capture.height >= 300 and
                            capture.convert("RGB").getextrema() != ((0, 0), (0, 0), (0, 0)),
                            f"{runtime_name}/{case}: native window capture produced")
                return output

            for runtime_name, command in (("source", [str(args.source_python.resolve()), str(ROOT / "main.py")]),
                                          ("frozen", [str(exe)])):
                workflow_output = smoke(command, runtime_name, sample_path, "workflow", workflow=True)
                workflow = read_json(workflow_output / "workflow.json")
                report["runtimes"][runtime_name] = {"workflow": workflow}
                persist()
                require(workflow["regions"] > 0 and workflow["erase_patches"] == workflow["regions"],
                        runtime_name + ": real OCR creates text regions and erasure patches")
                require(len(workflow["sources"]) == workflow["regions"] and
                        all(text.strip() and sum("\u3040" <= char <= "\u30ff" or
                            "\u3400" <= char <= "\u9fff" for char in text) >= 2
                            for text in workflow["sources"]),
                        runtime_name + ": actual OCR produces Japanese text; raw result retained for review")
                require(len(workflow["targets"]) == workflow["regions"] and
                        all(text.strip() and any("\uac00" <= char <= "\ud7a3" for char in text)
                            for text in workflow["targets"]),
                        runtime_name + ": actual local translation produces Korean drafts")
                reopened_workflow = smoke(command, runtime_name, workflow_output / "output.twproj", "workflow-reopened")
                _, _, workflow_pixels = collection(reopened_workflow, runtime_name + "/workflow-reopened")
                require(workflow_pixels == [png_hash(workflow_output / "output.png")],
                        runtime_name + ": translated project reopens with identical pixels")

                pdf_output = smoke(command, runtime_name, native_path, "pdf-import")
                manifest, assets, page_pixels = collection(pdf_output, runtime_name + "/pdf-import")
                require(len(manifest["pages"]) == len(page_kinds) and
                        all(not page["objects"] and not page["ocr_done"] for page in manifest["pages"]),
                        runtime_name + ": PDF import leaves sentence selection manual")
                for index, page in enumerate(manifest["pages"]):
                    require(bool(page["clean_asset"]) and page["clean_asset"] in assets,
                            f"{runtime_name}: {page_kinds[index]} has a self-contained clean asset")
                    with Image.open(BytesIO(assets[page["clean_asset"]])) as clean:
                        require(pixel_hash(clean) == references[index],
                                f"{runtime_name}: {page_kinds[index]} restores exact text-free background pixels")
                    with Image.open(BytesIO(assets[page["asset"]])) as original:
                        require(pixel_hash(original) == page_pixels[index] != references[index],
                                f"{runtime_name}: {page_kinds[index]} preserves original page pixels")
                reopened = smoke(command, runtime_name, pdf_output / "output.twproj", "pdf-reopened")
                reopened_manifest, reopened_assets, reopened_pixels = collection(reopened, runtime_name + "/pdf-reopened")
                require(reopened_pixels == page_pixels and reopened_manifest == manifest and reopened_assets == assets,
                        runtime_name + ": PDF project reopens with identical document, assets, and exported pixels")
                report["runtimes"][runtime_name] = {
                    "workflow": workflow, "workflow_pixel_sha256": workflow_pixels,
                    "pdf_page_pixel_sha256": page_pixels,
                    "native_capture": str(pdf_output / "window.png"),
                    "project": str(pdf_output / "output.twproj"),
                }
                persist()

        source, frozen = (report["runtimes"][name] for name in ("source", "frozen"))
        require(source["workflow"] == frozen["workflow"] and
                source["workflow_pixel_sha256"] == frozen["workflow_pixel_sha256"] and
                source["pdf_page_pixel_sha256"] == frozen["pdf_page_pixel_sha256"],
                "source and recovered frozen runtimes agree on OCR, translation, and output pixels")
        require(all(sha256(Path(path).read_bytes()) == digest for path, digest in fixture_hashes.items()),
                "all generated input files remain unchanged")
        require(sha256(exe.read_bytes()) == EXPECTED_EXE_SHA256,
                "verification leaves the recovered executable unchanged")
        report.update({"passed": True, "status": "completed"})
        return 0
    except Exception as exc:
        report.update({"passed": False, "status": "failed", "error": str(exc),
                       "traceback": traceback.format_exc()})
        print("FAIL: " + str(exc), file=sys.stderr, flush=True)
        return 1
    finally:
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        persist()
        print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]),
                          "result": str(run / "result.json")}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
