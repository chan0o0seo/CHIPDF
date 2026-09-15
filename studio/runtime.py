"""Process-lifetime installation guard, independent of project or user data."""
import configparser
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re

APP_ID = '3A2EF1A7-51E4-4D2F-8121-F1C5EDE795AC'
APP_MUTEX = 'TranslationStudio.App.' + APP_ID
_guards = []


def installation_mutex(app_dir):
    """Only the isolated test installer may use a separate product namespace."""
    marker = Path(app_dir) / 'translation-studio.install.ini'
    try:
        if marker.stat().st_size > 8192:
            return APP_MUTEX
        raw = marker.read_bytes()
        # Inno's Windows INI writer may use either UTF-16 or the local ANSI code
        # page. Identity fields are ASCII, independent of the wizard language.
        text = raw.decode('utf-16') if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else raw.decode('utf-8-sig')
        values = configparser.ConfigParser(interpolation=None)
        values.read_string(text)
        app_id = values.get('Installation', 'AppId', fallback='')
        mutex = values.get('Installation', 'MutexName', fallback='')
        if re.fullmatch(r'TranslationStudio\.QA\.[a-z0-9]{8,32}', app_id) and mutex == app_id + '.App':
            return mutex
    except (OSError, ValueError, UnicodeError, configparser.Error):
        pass
    return APP_MUTEX


class InstallationGuard:
    """Keep the mutex alive in every app process; multiple editors may coexist."""
    def __init__(self, name=APP_MUTEX):
        self.name, self.handle = name, None
        if os.name == 'nt':
            self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            self.kernel.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
            self.kernel.CreateMutexW.restype = wintypes.HANDLE
            self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            self.kernel.CloseHandle.restype = wintypes.BOOL
            self.handle = self.kernel.CreateMutexW(None, False, name)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        # Explicit release is for tests. Production guards live until Windows
        # closes process handles after Qt and its workers have terminated.
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def protect_running_app(app_dir):
    guard = InstallationGuard(installation_mutex(app_dir))
    _guards.append(guard)
    return guard
