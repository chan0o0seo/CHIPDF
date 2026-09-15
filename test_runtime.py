"""Real Windows mutex lifetime and installed QA namespace isolation."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from studio.runtime import APP_MUTEX, InstallationGuard, installation_mutex


class RuntimeTests(unittest.TestCase):
    def test_portable_and_bad_marker_use_stable_production_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(installation_mutex(root), APP_MUTEX)
            marker = root / 'translation-studio.install.ini'
            for text in ('broken file', '[Installation]\nAppId=Other.App\nMutexName=Other.App', 'a'*9000):
                marker.write_text(text, 'utf-8')
                self.assertEqual(installation_mutex(root), APP_MUTEX)

    def test_installed_qa_scope_matches_both_ansi_and_utf16_ini(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app_id = 'TranslationStudio.QA.' + uuid4().hex
            for encoding in ('utf-8', 'utf-16'):
                (root / 'translation-studio.install.ini').write_text(
                    f'[Installation]\nAppId={app_id}\nMutexName={app_id}.App\nVersion=0.7.0\n', encoding)
                self.assertEqual(installation_mutex(root), app_id + '.App')
            (root / 'translation-studio.install.ini').write_text(
                f'[Installation]\nAppId={app_id}\nMutexName=Other.App\n', 'utf-8')
            self.assertEqual(installation_mutex(root), APP_MUTEX)

    @unittest.skipUnless(os.name == 'nt', 'Windows mutex test')
    def test_all_running_editor_handles_keep_installation_blocked(self):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
        kernel.OpenMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        name = 'TranslationStudio.QA.' + uuid4().hex + '.App'
        def exists():
            handle = kernel.OpenMutexW(0x00100000, False, name)
            if handle:
                kernel.CloseHandle(handle)
            return bool(handle)
        self.assertFalse(exists())
        first, second = InstallationGuard(name), InstallationGuard(name)
        try:
            self.assertTrue(exists())
            first.close()
            self.assertTrue(exists())
            second.close()
            self.assertFalse(exists())
        finally:
            first.close()
            second.close()


if __name__ == '__main__':
    unittest.main()
