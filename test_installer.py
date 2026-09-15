"""Fail-closed gates before native installer QA may touch per-user Windows state."""
from copy import deepcopy
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from verify_installer import (QA, contained, metadata, verify_refusal_log, read_shell_link,
                              _shell_link_interfaces, _com_method, _check_hresult)


class InstallerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='installer-gates-', dir=QA)
        self.root = Path(self.temp.name)
        self.exe = self.root / '허가된 QA 설치.exe'
        self.exe.write_bytes(b'Never execute this fixture; metadata validation only.')
        self.value = {'qa': True, 'version': '0.7.0', 'app_id': 'TranslationStudio.QA.test1234',
                      'group_name': 'Translation Studio QA test1234', 'mutex_name': 'TranslationStudio.QA.test1234.App',
                      'uninstall_key': r'Software\Microsoft\Windows\CurrentVersion\Uninstall\TranslationStudio.QA.test1234_is1',
                      'installer': str(self.exe), 'sha256': hashlib.sha256(self.exe.read_bytes()).hexdigest(),
                      'source_exe_sha256': hashlib.sha256(self.exe.read_bytes()).hexdigest()}

    def tearDown(self):
        self.temp.cleanup()

    def check(self, **changes):
        value = deepcopy(self.value)
        value.update(changes)
        path = self.root / 'installer-qa.json'
        path.write_text(json.dumps(value), 'utf-8')
        return metadata(path)

    def test_accept_verified_isolated_payload(self):
        self.assertEqual(self.check()['installer'], str(self.exe.resolve()))

    def test_reject_production_or_truthy_non_boolean_flag(self):
        for qa in (False, 'true', 1, None):
            with self.subTest(qa=qa), self.assertRaisesRegex(ValueError, 'production'):
                self.check(qa=qa)

    def test_reject_production_and_path_like_app_ids(self):
        for app_id in ('TranslationStudio', 'TranslationStudio.QA.../production', r'TranslationStudio.QA.abc\def'):
            with self.subTest(app_id=app_id), self.assertRaisesRegex(ValueError, 'isolated'):
                self.check(app_id=app_id)

    def test_reject_cross_namespace_registry_shortcuts_and_mutex(self):
        for key in ('group_name', 'mutex_name', 'uninstall_key'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check(**{key: 'TranslationStudio'})

    def test_reject_tampered_installer_before_execution(self):
        self.exe.write_bytes(b'Payload changed after compilation')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.check()

    def test_reject_installer_outside_artifact_roots(self):
        with self.assertRaisesRegex(ValueError, 'inside'):
            self.check(installer=str(QA.parent / 'Translation Studio.exe'))

    def test_reject_invalid_version(self):
        for version in ('', 'new', '0.7 beta', '0.7.1.2.3'):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'version'):
                self.check(version=version)

    def test_containment_excludes_root_and_traversal(self):
        self.assertEqual(contained(self.root / 'nested' / 'file', self.root), self.root / 'nested' / 'file')
        for path in (self.root, self.root / '..' / 'foreign'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                contained(path, self.root)

    def test_refusal_requires_intended_reason_and_no_runtime_error(self):
        log = self.root / 'refusal.log'
        reason = 'Translation Studio refused downgrade'
        log.write_text(reason, 'utf-8')
        verify_refusal_log(log, reason)
        for text in ('Runtime error: Unknown constant userprofile', reason + '\nRuntime error: invalid call'):
            with self.subTest(text=text):
                log.write_text(text, 'utf-8')
                with self.assertRaises(AssertionError):
                    verify_refusal_log(log, reason)

    def test_native_shortcut_reader_preserves_non_ansi_path(self):
        # 捩 cannot be represented in the Korean Windows ANSI code page. The
        # former WScript.Shell reader returned '?' despite a correct .lnk file.
        target = self.root / '捩花 한글 공백.exe'
        target.write_bytes(b'Owned path fixture; never executed.')
        shortcut = self.root / '유니코드 바로 가기.lnk'
        with _shell_link_interfaces() as (shell, persist):
            _check_hresult(_com_method(shell, 20, wintypes.LPCWSTR)(shell, str(target)))
            _check_hresult(_com_method(shell, 9, wintypes.LPCWSTR)(shell, str(self.root)))
            _check_hresult(_com_method(shell, 11, wintypes.LPCWSTR)(shell, '--sample "한글"'))
            _check_hresult(_com_method(persist, 6, wintypes.LPCWSTR, wintypes.BOOL)(persist, str(shortcut), True))
        value = read_shell_link(shortcut)
        self.assertEqual(Path(value['target']), target)
        self.assertEqual(Path(value['working_directory']), self.root)
        self.assertEqual(value['arguments'], '--sample "한글"')


if __name__ == '__main__':
    unittest.main()
