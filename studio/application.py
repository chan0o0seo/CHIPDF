"""Receive Finder's document-open events through Qt, including during startup."""
from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QApplication


class StudioApplication(QApplication):
    def __init__(self, args):
        super().__init__(args)
        self.editor = None
        self.pending_files = []
        self.open_timer = QTimer(self)
        self.open_timer.setSingleShot(True)
        self.open_timer.timeout.connect(self.open_pending_files)

    def event(self, event):
        if event.type() == QEvent.FileOpen:
            path = event.file()
            if path:
                self.pending_files.append(path)
                self.open_timer.start(0)
                event.accept()
                return True
        return super().event(event)

    def set_editor(self, editor):
        self.editor = editor
        if self.pending_files:
            self.open_timer.start(0)

    def open_pending_files(self):
        if self.editor is None or not self.pending_files:
            return
        if self.editor.io_job:
            self.open_timer.start(100)
            return
        # Projects are independent documents; avoid mixing separate Finder events
        # into one import request or dropping events while an import is running.
        self.editor.open_path(self.pending_files.pop(0))
        if self.pending_files:
            self.open_timer.start(100)
