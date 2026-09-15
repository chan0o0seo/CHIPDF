from threading import Event
from PySide6.QtCore import QObject, QRunnable, Signal


class Signals(QObject):
    progress = Signal(str)
    finished = Signal(object)


class Job(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.cancelled = Event()
        self.signals = Signals()

    def run(self):
        try:
            value = self.operation(self.cancelled, self.signals.progress.emit)
            result = {"value": value, "cancelled": self.cancelled.is_set(), "error": None}
        except Exception as exc:
            result = {"value": None, "cancelled": self.cancelled.is_set(), "error": str(exc)}
        self.signals.finished.emit(result)
