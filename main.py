"""Development and frozen entry point. Local dependencies never change global Python."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(ROOT / ".deps"))
    sys.path.insert(0, str(ROOT))


def main():
    import argparse
    import os

    from studio import APP_NAME
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("file", nargs="?")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--smoke-dir", type=Path, help="Write a widget capture and exit (build verification).")
    parser.add_argument("--smoke-workflow", action="store_true", help="Also run OCR and local translation (build verification).")
    parser.add_argument("--smoke-collection", action="store_true", help="Export every page as PNG/PDF (build verification).")
    args = parser.parse_args()
    if (args.smoke_workflow or args.smoke_collection) and not args.smoke_dir:
        parser.error("Workflow/collection verification requires --smoke-dir")
    def trace(message):
        if args.smoke_dir:
            args.smoke_dir.mkdir(parents=True, exist_ok=True)
            with (args.smoke_dir / "startup.log").open("a", encoding="utf-8") as stream:
                stream.write(message + "\n")
    trace("Python entry started")
    from studio.runtime import protect_running_app
    guard = protect_running_app(Path(sys.executable).parent if getattr(sys, 'frozen', False) else ROOT)
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        set_app_id = ctypes.WinDLL('shell32').SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [wintypes.LPCWSTR]
        set_app_id.restype = ctypes.c_long
        set_app_id(guard.name)
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication
    from studio.window import Editor
    trace("Qt imports completed")
    QApplication.setAttribute(Qt.AA_Use96Dpi)
    app = QApplication(sys.argv[:1])
    trace("QApplication created")
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("Translation Studio")
    app.setWindowIcon(QIcon(str(ROOT / 'assets' / 'chipdf.png')))
    app.setFont(QFont("맑은 고딕", 10))
    data_dir = args.data_dir or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "TranslationStudio"
    editor = Editor(data_dir, auto_ocr=args.smoke_workflow)
    trace("Editor created")
    editor.show()
    if args.file:
        if args.smoke_dir:
            editor.load_path(Path(args.file))
        else:
            QTimer.singleShot(0, lambda: editor.open_path(args.file))
    trace("Document opened")
    if args.smoke_dir:
        def capture():
            try:
                import json
                from studio import __version__
                (args.smoke_dir / 'smoke-state.json').write_text(json.dumps({
                    'version': __version__, 'data_dir': str(data_dir.resolve()),
                    'auto_ocr': editor.auto_ocr, 'canvas_tool': editor.canvas.tool,
                    'mutex_name': guard.name, 'presets_load_error': editor.presets_load_error,
                    'saved_style_names': sorted(editor.presets['styles']),
                    'saved_layout_names': sorted(editor.presets['layouts']),
                }, ensure_ascii=False, indent=2), 'utf-8')
                editor.grab().save(str(args.smoke_dir / "window.png"))
                if editor.project:
                    editor.export_to(args.smoke_dir / "output.png")
                    if args.smoke_collection:
                        import json
                        indices = list(range(len(editor.project.pages)))
                        editor.export_pages(args.smoke_dir / 'pages', indices, 'png')
                        editor.export_pages(args.smoke_dir / 'output.pdf', indices, 'pdf')
                        editor.save_to(args.smoke_dir / 'output.twproj')
                        editor.switch_page(indices[-1])
                        editor.export_to(args.smoke_dir / 'last.png')
                        (args.smoke_dir / 'collection.json').write_text(json.dumps({
                            'pages': len(indices), 'names': [p.name for p in editor.project.pages],
                            'physical_sizes': [[p.width_pt, p.height_pt] for p in editor.project.pages],
                        }, ensure_ascii=False, indent=2), 'utf-8')
                    if args.smoke_workflow:
                        import json
                        editor.save_to(args.smoke_dir / "output.twproj")
                        from studio.model import TextBox
                        objects = [o for o in editor.project.pages[0].objects if isinstance(o, TextBox)]
                        if not objects or not all(o.source_text and o.text for o in objects):
                            raise ValueError("OCR/translation did not produce all drafts")
                        (args.smoke_dir / "workflow.json").write_text(json.dumps({
                            "regions": len(objects), "sources": [o.source_text for o in objects],
                            "targets": [o.text for o in objects], "erase_patches": sum(bool(o.erase_patch) for o in objects),
                        }, ensure_ascii=False, indent=2), "utf-8")
                (args.smoke_dir / "ok.txt").write_text("native window started; export completed", "utf-8")
                editor.close()
            except Exception:
                import traceback
                trace(traceback.format_exc())
                app.exit(1)
        if args.smoke_workflow:
            import time
            deadline = time.monotonic() + 120
            phase = ["ocr"]
            timer = QTimer(editor)
            timer.setInterval(100)
            def advance():
                if editor.last_error or time.monotonic() > deadline:
                    timer.stop()
                    trace(editor.last_error or "Workflow timeout")
                    editor.cancel_job()
                    app.exit(1)
                elif editor.job is None and not editor.pending_ocr:
                    if phase[0] == "ocr":
                        phase[0] = "translation"
                        trace("OCR completed")
                        editor.translate_missing()
                    else:
                        timer.stop()
                        trace("Translation completed")
                        capture()
            timer.timeout.connect(advance)
            timer.start()
        else:
            QTimer.singleShot(900, capture)
    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        if "--smoke-dir" in sys.argv:
            import traceback
            output = Path(sys.argv[sys.argv.index("--smoke-dir") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "error.log").write_text(traceback.format_exc(), "utf-8")
            raise SystemExit(1)
        raise
