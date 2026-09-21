"""OS defaults, Chrome discovery, Unicode OCR paths and Finder event delivery."""
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_studio as base
from PySide6.QtGui import QFileOpenEvent
from studio.application import StudioApplication
from studio import platform_support, chrome_translation, recognition
from studio.model import Style


class PlatformTests(unittest.TestCase):
    def test_mac_data_directory_shared_by_models_and_app(self):
        from studio.model_packs import default_data_dir
        from studio.inpaint_engine import _model_candidates
        with patch.object(platform_support.sys, 'platform', 'darwin'), patch.dict(os.environ, {'CHIPDF_LAMA_MODEL': ''}):
            expected = Path.home() / 'Library/Application Support/TranslationStudio'
            self.assertEqual(default_data_dir(), expected)
            self.assertEqual(_model_candidates()[-1], expected / 'models/inpaint/lama_fp32.onnx')
            self.assertEqual(Style().family, 'Apple SD Gothic Neo')
            self.assertEqual(Style(family='맑은 고딕').family, '맑은 고딕')

    def test_windows_keeps_existing_data_location(self):
        with patch.object(platform_support.sys, 'platform', 'win32'), patch.dict(os.environ, {'LOCALAPPDATA': str(base.ROOT)}):
            self.assertEqual(platform_support.default_data_dir(), base.ROOT / 'TranslationStudio')
            self.assertEqual(Style().family, '맑은 고딕')

    def test_mac_chrome_system_and_user_installations(self):
        for folder in (Path('/Applications'), Path.home() / 'Applications'):
            expected = folder / 'Google Chrome.app/Contents/MacOS/Google Chrome'
            with patch.object(chrome_translation.sys, 'platform', 'darwin'), patch.object(
                    Path, 'is_file', lambda p: p == expected):
                self.assertEqual(chrome_translation.chrome_executable(), expected)

    def test_mac_unicode_ocr_path_does_not_call_windows_path_api(self):
        with patch.object(recognition.sys, 'platform', 'darwin'), patch.object(
                Path, 'read_bytes', return_value=b'model'), patch.object(recognition.tempfile, 'gettempdir') as cache:
            self.assertEqual(recognition.model_path(), base.ROOT / 'vendor/tessdata')
            cache.assert_not_called()

    def test_finder_events_queue_until_editor_ready_and_import_finished(self):
        app = SimpleNamespace(editor=None, pending_files=[], open_timer=Mock())
        event = QFileOpenEvent(str(base.ROOT / '작업.twproj'))
        self.assertTrue(StudioApplication.event(app, event))
        StudioApplication.open_pending_files(app)
        self.assertEqual(len(app.pending_files), 1)
        editor = SimpleNamespace(io_job=object(), open_path=Mock())
        StudioApplication.set_editor(app, editor)
        StudioApplication.open_pending_files(app)
        editor.open_path.assert_not_called()
        self.assertEqual(len(app.pending_files), 1)
        editor.io_job = None
        StudioApplication.open_pending_files(app)
        editor.open_path.assert_called_once_with(str(base.ROOT / '작업.twproj'))
        self.assertEqual(app.pending_files, [])


if __name__ == '__main__':
    unittest.main()
