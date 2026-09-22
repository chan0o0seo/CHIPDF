"""Development and frozen entry point. Local dependencies never change global Python."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(ROOT / ".deps"))
    sys.path.insert(0, str(ROOT))


def main():
    import argparse

    from studio import APP_NAME
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("file", nargs="?")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
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
    from studio.application import StudioApplication
    from studio.platform_support import default_data_dir, default_font_family
    from studio.window import Editor
    QApplication.setAttribute(Qt.AA_Use96Dpi)
    app = StudioApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("Translation Studio")
    app.setWindowIcon(QIcon(str(ROOT / 'assets' / 'chipdf.png')))
    app.setFont(QFont(default_font_family(), 10))
    data_dir = args.data_dir or default_data_dir()
    editor = Editor(data_dir)
    editor.show()
    app.set_editor(editor)
    if args.file:
        QTimer.singleShot(0, lambda: editor.open_path(args.file))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
