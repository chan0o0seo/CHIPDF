"""Exercise isolated Inno installers without installing the production identity.

Usage: python verify_installer.py --previous-metadata old/installer-qa.json
                                 --current-metadata new/installer-qa.json

Sidecars must describe compiler-generated QA installers, including their SHA-256.
The verifier refuses an existing QA registry entry or shortcut group. All projects,
installer logs and captures are retained below qa/install-<random>/ for inspection.
It only removes installed payload using that QA installation's own uninstaller.

Exit-code contracts: https://jrsoftware.org/ishelp/topic_setupexitcodes.htm and
https://jrsoftware.org/ishelp/topic_uninstexitcodes.htm (checked 2026-09-13).
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parent
QA = ROOT / 'qa'


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def contained(path, parent):
    path, parent = Path(path).resolve(), Path(parent).resolve()
    if path == parent or not path.is_relative_to(parent):
        raise ValueError(f'Expected a child of {parent}: {path}')
    return path


def metadata(path):
    value = json.loads(Path(path).read_text('utf-8'))
    if value.get('qa') is not True:
        raise ValueError('Refusing production installer: sidecar must contain qa=true')
    match = re.fullmatch(r'TranslationStudio\.QA\.([a-z0-9]{8,32})', value.get('app_id', ''))
    if not match:
        raise ValueError('Installer AppId must use the isolated TranslationStudio.QA namespace')
    token = match.group(1)
    if value.get('group_name') != f'Translation Studio QA {token}' or value.get('mutex_name') != f'TranslationStudio.QA.{token}.App':
        raise ValueError('QA shortcut group or mutex does not match the isolated AppId')
    expected_key = rf'Software\Microsoft\Windows\CurrentVersion\Uninstall\{value["app_id"]}_is1'
    if value.get('uninstall_key') != expected_key:
        raise ValueError('QA uninstall registry key does not match the isolated AppId')
    if not re.fullmatch(r'\d+\.\d+(?:\.\d+){0,2}', value.get('version', '')):
        raise ValueError('Installer version is missing or invalid')
    if not re.fullmatch(r'[0-9a-f]{64}', value.get('source_exe_sha256', '')):
        raise ValueError('Release executable hash is missing or invalid')
    installer = Path(value['installer']).resolve()
    if not installer.is_relative_to(ROOT / 'dist') and not installer.is_relative_to(QA):
        raise ValueError('QA installer must be inside this project dist or qa directory')
    if installer.suffix.lower() != '.exe' or digest(installer) != value.get('sha256'):
        raise ValueError('QA installer hash mismatch')
    value['installer'] = str(installer)
    return value


def system_environment():
    env = os.environ.copy()
    for key in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QT_QPA_PLATFORM'):
        env.pop(key, None)
    system = Path(os.environ['SystemRoot'])
    env['PATH'] = str(system / 'System32') + os.pathsep + str(system)
    return env


class _GUID(ctypes.Structure):
    _fields_ = [('data', ctypes.c_ubyte * 16)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


def _com_method(pointer, index, *argument_types):
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argument_types)(table[index])


def _check_hresult(value):
    if value < 0:
        raise OSError(f'Windows Shell COM failed: HRESULT 0x{value & 0xffffffff:08x}')


@contextmanager
def _shell_link_interfaces():
    ole = ctypes.WinDLL('ole32')
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoCreateInstance.argtypes = [ctypes.POINTER(_GUID), ctypes.c_void_p, wintypes.DWORD,
                                     ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
    ole.CoCreateInstance.restype = ctypes.c_long
    initialized = ole.CoInitializeEx(None, 2)
    # Another native component may already have initialized COM as MTA.
    if initialized != -2147417850:  # RPC_E_CHANGED_MODE: use the existing apartment.
        _check_hresult(initialized)
    shell, persist = ctypes.c_void_p(), ctypes.c_void_p()
    try:
        clsid = _GUID.parse('00021401-0000-0000-c000-000000000046')
        interface = _GUID.parse('000214f9-0000-0000-c000-000000000046')  # IShellLinkW
        _check_hresult(ole.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(interface), ctypes.byref(shell)))
        file_interface = _GUID.parse('0000010b-0000-0000-c000-000000000046')  # IPersistFile
        _check_hresult(_com_method(shell, 0, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))(
            shell, ctypes.byref(file_interface), ctypes.byref(persist)))
        yield shell, persist
    finally:
        if persist:
            _com_method(persist, 2)(persist)
        if shell:
            _com_method(shell, 2)(shell)
        if initialized >= 0:
            ole.CoUninitialize()


def read_shell_link(path):
    """Read UTF-16 paths directly; WScript.Shell loses non-ANSI characters.

    IShellLinkW contract: https://learn.microsoft.com/en-us/windows/win32/api/
    shobjidl_core/nf-shobjidl_core-ishelllinkw-getpath
    """
    with _shell_link_interfaces() as (shell, persist):
        _check_hresult(_com_method(persist, 5, wintypes.LPCWSTR, wintypes.DWORD)(persist, str(Path(path).resolve()), 0))
        target, working, arguments = (ctypes.create_unicode_buffer(32768) for _ in range(3))
        _check_hresult(_com_method(shell, 3, wintypes.LPWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)(
            shell, target, len(target), None, 4))  # SLGP_RAWPATH
        _check_hresult(_com_method(shell, 8, wintypes.LPWSTR, ctypes.c_int)(shell, working, len(working)))
        _check_hresult(_com_method(shell, 10, wintypes.LPWSTR, ctypes.c_int)(shell, arguments, len(arguments)))
        return {'target': target.value, 'working_directory': working.value, 'arguments': arguments.value}


def registry_values(key):
    import winreg
    found = []
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_READ | view) as handle:
                count = winreg.QueryInfoKey(handle)[1]
                found.append({name: value for name, value, _ in (winreg.EnumValue(handle, n) for n in range(count))})
        except FileNotFoundError:
            pass
    if not found:
        return None
    if any(value != found[0] for value in found):
        raise AssertionError('QA uninstall registry views disagree')
    return found[0]


def verify_refusal_log(path, expected_reasons):
    raw = Path(path).read_bytes()
    text = raw.decode('utf-16') if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else raw.decode('utf-8-sig', errors='replace')
    if isinstance(expected_reasons, str):
        expected_reasons = (expected_reasons,)
    if not expected_reasons or not any(reason in text for reason in expected_reasons):
        raise AssertionError(f'Refusal did not report its intended reason: {path}\n{text[-1600:]}')
    if re.search(r'Runtime error|Unknown constant|Internal error', text, re.IGNORECASE):
        raise AssertionError(f'Installer runtime error is not a successful protective refusal: {path}')


class NativeWindows:
    """Read/control only windows in a subprocess tree started by this verifier."""
    def __init__(self):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        # PrintWindow emits physical pixels. Match GetWindowRect to that scale
        # before reading any HWND, otherwise a 125% desktop crops the capture.
        self.user.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        self.user.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        if not self.user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.user.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.GetDlgItem.restype = wintypes.HWND
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user.EnumWindows.argtypes = [self.callback_type, wintypes.LPARAM]
        self.kernel.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.OpenMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.known_pids = set()

    def process_tree(self, root):
        class Process(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD), ('pid', wintypes.DWORD),
                        ('heap', ctypes.c_size_t), ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
                        ('parent', wintypes.DWORD), ('priority', wintypes.LONG), ('flags', wintypes.DWORD),
                        ('exe', wintypes.WCHAR * 260)]
        self.kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self.kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Process)]
        self.kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Process)]
        handle = self.kernel.CreateToolhelp32Snapshot(2, 0)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        parents = {}
        try:
            row = Process()
            row.size = ctypes.sizeof(row)
            ok = self.kernel.Process32FirstW(handle, ctypes.byref(row))
            while ok:
                parents[row.pid] = row.parent
                ok = self.kernel.Process32NextW(handle, ctypes.byref(row))
        finally:
            self.kernel.CloseHandle(handle)
        pids = {root}
        for _ in range(12):
            expanded = pids | {pid for pid, parent in parents.items() if parent in pids}
            if expanded == pids:
                break
            pids = expanded
        return pids

    def windows(self, pid):
        pids, output = self.process_tree(pid), []
        def visit(hwnd, _):
            process = wintypes.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
            if process.value in pids and self.user.IsWindowVisible(hwnd):
                text = ctypes.create_unicode_buffer(self.user.GetWindowTextLengthW(hwnd) + 1)
                self.user.GetWindowTextW(hwnd, text, len(text))
                output.append((hwnd, text.value))
            return True
        self.user.EnumWindows(self.callback_type(visit), 0)
        return output

    def mutex_exists(self, name):
        handle = self.kernel.OpenMutexW(0x100000, False, name)
        if handle:
            self.kernel.CloseHandle(handle)
            return True
        if ctypes.get_last_error() not in (0, 2):
            raise ctypes.WinError(ctypes.get_last_error())
        return False

    def capture(self, hwnd, path):
        # PrintWindow captures this QA window alone, even if another app overlaps it.
        self.user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user.GetWindowDC.argtypes = [wintypes.HWND]
        self.user.GetWindowDC.restype = wintypes.HDC
        self.user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self.user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
        gdi = ctypes.WinDLL('gdi32', use_last_error=True)
        gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi.CreateCompatibleDC.restype = wintypes.HDC
        gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi.SelectObject.restype = wintypes.HGDIOBJ
        gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi.DeleteDC.argtypes = [wintypes.HDC]
        gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                                 ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        class Header(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('width', wintypes.LONG), ('height', wintypes.LONG),
                        ('planes', wintypes.WORD), ('bits', wintypes.WORD), ('compression', wintypes.DWORD),
                        ('image_size', wintypes.DWORD), ('xppm', wintypes.LONG), ('yppm', wintypes.LONG),
                        ('colors', wintypes.DWORD), ('important', wintypes.DWORD)]
        rect = wintypes.RECT()
        if not self.user.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if not 50 <= width <= 10000 or not 50 <= height <= 10000:
            raise AssertionError('QA window has invalid capture dimensions')
        dc = self.user.GetWindowDC(hwnd)
        memory = gdi.CreateCompatibleDC(dc)
        bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
        previous = gdi.SelectObject(memory, bitmap)
        try:
            if not self.user.PrintWindow(hwnd, memory, 2):
                raise AssertionError('Native wizard PrintWindow failed')
            gdi.SelectObject(memory, previous)
            header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
            pixels = ctypes.create_string_buffer(width * height * 4)
            if not gdi.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(header), 0):
                raise ctypes.WinError(ctypes.get_last_error())
            sys.path.insert(0, str(ROOT / '.deps'))
            from PIL import Image
            Image.frombytes('RGB', (width, height), pixels.raw, 'raw', 'BGRX').save(path)
        finally:
            gdi.SelectObject(memory, previous)
            gdi.DeleteObject(bitmap)
            gdi.DeleteDC(memory)
            self.user.ReleaseDC(hwnd, dc)

    def close(self, process, *, confirm=False):
        deadline = time.monotonic() + 20
        sent = set()
        while process.poll() is None and time.monotonic() < deadline:
            for hwnd, title in self.windows(process.pid):
                yes = self.user.GetDlgItem(hwnd, 6) if confirm else None
                if yes:
                    self.user.PostMessageW(yes, 0x00F5, 0, 0)  # BM_CLICK, own confirmation only.
                elif hwnd not in sent:
                    self.user.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE: normal close/autosave.
                    sent.add(hwnd)
            time.sleep(.1)
        if process.poll() is None:
            raise AssertionError(f'QA process did not close normally; retained for diagnosis: PID {process.pid}')
        return process.returncode


class Verification:
    def __init__(self, previous, current):
        self.previous, self.current = previous, current
        for key in ('app_id', 'group_name', 'mutex_name', 'uninstall_key'):
            if previous[key] != current[key]:
                raise ValueError(f'Upgrade installers must have the same QA identity: {key}')
        if tuple(map(int, previous['version'].split('.'))) >= tuple(map(int, current['version'].split('.'))):
            raise ValueError('Previous installer must have an older version')
        self.env = system_environment()
        self.native = NativeWindows()
        self.probe = contained(QA / ('install-' + uuid.uuid4().hex[:10]), QA)
        self.app_dir = self.probe / '설치 위치 공백' / 'Translation Studio'
        self.data = self.probe / '사용자 작업 보관' / 'TranslationStudio'
        self.exe = self.app_dir / 'Translation Studio.exe'
        self.group = Path(os.environ['APPDATA']) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / current['group_name']
        if registry_values(current['uninstall_key']) is not None or self.group.exists():
            raise ValueError('QA identity already installed. Use a fresh compiler QA token; existing state is left untouched.')
        if self.native.mutex_exists(current['mutex_name']):
            raise ValueError('QA application mutex already exists; existing process is left untouched')
        self.probe.mkdir(parents=True)
        self.app_dir.mkdir(parents=True)  # Exercise installation into an existing empty dedicated directory.
        self.data.mkdir(parents=True)
        self.expected = {}
        self.report = {'probe': str(self.probe), 'qa_app_id': current['app_id'], 'old_version': previous['version'],
                       'new_version': current['version'], 'checks': {}, 'logs': []}
        self.write_report()

    def write_report(self):
        text = json.dumps(self.report, ensure_ascii=False, indent=2)
        (self.probe / 'result.json').write_text(text, 'utf-8')
        (QA / 'installer-result.json').write_text(text, 'utf-8')

    def checked(self, name, detail=True):
        self.report['checks'][name] = detail
        self.write_report()
        print('INSTALLER_CHECK=' + json.dumps({name: detail}, ensure_ascii=True), flush=True)

    def run_setup(self, package, label, destination=None, expected_success=True, expected_reasons=()):
        log = self.probe / f'{label}.log'
        args = [package['installer'], '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
                '/NOCLOSEAPPLICATIONS', '/NOFORCECLOSEAPPLICATIONS', '/NORESTARTAPPLICATIONS',
                '/TASKS=', f'/DIR={destination or self.app_dir}', f'/LOG={log}']
        result = subprocess.run(args, cwd=self.probe, env=self.env, timeout=240,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        self.report['logs'].append({'step': label, 'path': str(log), 'exit_code': result.returncode})
        self.write_report()
        if (result.returncode == 0) != expected_success:
            raise AssertionError(f'{label}: unexpected installer exit {result.returncode}; inspect {log}')
        if expected_success:
            assert digest(self.exe) == package['source_exe_sha256'], 'Installed executable does not match the verified release payload'
        else:
            verify_refusal_log(log, expected_reasons)
        return result.returncode

    def uninstall(self, label, expected_success=True, expected_reasons=()):
        entries = registry_values(self.current['uninstall_key'])
        if entries is None:
            raise AssertionError('QA uninstall registry entry is missing')
        command = entries['UninstallString']
        match = re.fullmatch(r'"([^"]+\.exe)"', command, re.IGNORECASE)
        if not match:
            raise AssertionError('UninstallString must quote the complete executable path')
        executable = contained(match.group(1), self.app_dir)
        if not re.fullmatch(r'unins\d+\.exe', executable.name, re.IGNORECASE):
            raise AssertionError('Unexpected QA uninstaller name')
        log = self.probe / f'{label}.log'
        result = subprocess.run([str(executable), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', f'/LOG={log}'],
                                cwd=self.probe, env=self.env, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
        self.report['logs'].append({'step': label, 'path': str(log), 'exit_code': result.returncode})
        self.write_report()
        if (result.returncode == 0) != expected_success:
            raise AssertionError(f'{label}: unexpected uninstaller exit {result.returncode}; inspect {log}')
        if expected_success:
            deadline = time.monotonic() + 10
            while (self.exe.exists() or registry_values(self.current['uninstall_key']) is not None) and time.monotonic() < deadline:
                time.sleep(.1)
            assert not self.exe.exists(), 'Owned application executable was not uninstalled'
            assert registry_values(self.current['uninstall_key']) is None, 'QA Apps entry survived uninstall'
            assert not self.group.exists(), 'QA Start Menu shortcut group survived uninstall'
        else:
            verify_refusal_log(log, expected_reasons)
        return result.returncode

    def add_preserved(self, path, source):
        path = contained(path, self.probe)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, path)
        self.expected[str(path)] = digest(path)

    def assert_preserved(self):
        for path, expected in self.expected.items():
            assert Path(path).exists() and digest(path) == expected, f'User file changed: {path}'

    def shortcut_hashes(self):
        return {str(path): digest(path) for path in self.group.glob('*.lnk')}

    def seed_user_data(self):
        fixture = ROOT / 'qa' / 'vertical-06' / '작업.twproj'
        with zipfile.ZipFile(fixture) as archive:
            manifest = json.loads(archive.read('manifest.json'))
        recovery = self.data / 'recovery' / f'{manifest["id"]}.twproj'
        self.add_preserved(recovery, fixture)
        self.add_preserved(recovery.with_suffix('.twproj.bak'), fixture)
        self.add_preserved(self.data / 'presets.json', ROOT / 'qa' / 'vertical-06' / 'data' / 'presets.json')
        # Opening a recovery archive deliberately resumes it with autosave.
        # Exercise the app using the normal saved document, while recovery and
        # its backup remain idle and byte-for-byte protected through every step.
        self.project = self.probe / '내 문서' / '편집 작업.twproj'
        self.add_preserved(self.project, fixture)

    def verify_registration(self, version):
        value = registry_values(self.current['uninstall_key'])
        assert value is not None and value['DisplayVersion'] == version
        assert Path(value['InstallLocation']).resolve() == self.app_dir.resolve()
        assert self.group.exists(), 'Start Menu group missing'
        links = sorted(self.group.glob('*.lnk'))
        assert links, 'Start Menu application shortcut missing'
        found = []
        for link in links:
            info = read_shell_link(link)
            if Path(info['target']).name == self.exe.name:
                found.append(info)
        assert len(found) == 1 and Path(found[0]['target']).resolve() == self.exe.resolve(), 'Shortcut target did not survive spaces/Korean path'
        assert not found[0]['arguments'], 'Shortcut unexpectedly adds runtime arguments'
        command = value.get('UninstallString', '')
        assert re.fullmatch(r'"[^\"]+\\unins\d+\.exe"', command, re.IGNORECASE), 'UninstallString is not fully quoted'
        return {'display_version': value['DisplayVersion'], 'shortcut_target': found[0]['target'], 'uninstall_string': command}

    def smoke(self, label):
        output = self.probe / label
        result = subprocess.run([str(self.exe), str(self.project), '--data-dir', str(self.data), '--smoke-dir', str(output), '--smoke-collection'],
                                cwd=self.probe, env=self.env, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0 and (output / 'ok.txt').exists(), f'Installed app smoke failed: {output}'
        expected = json.loads((ROOT / 'qa' / 'vertical-06' / 'result.json').read_text('utf-8'))
        actual = [digest(path) for path in sorted((output / 'pages').glob('*.png'))]
        assert actual == expected['page_png_sha256'], 'Installed vertical/mixed text PNG differs'
        saved = output / 'output.twproj'
        with zipfile.ZipFile(saved) as archive:
            manifest = json.loads(archive.read('manifest.json'))
        app_version = self.previous['version'] if label == 'previous-version' else self.current['version']
        version_numbers = tuple(map(int, app_version.split('.')))
        expected_schema = 8 if version_numbers >= (0, 8, 1) else 7 if version_numbers >= (0, 8, 0) else 6
        assert manifest['version'] == expected_schema
        assert sum(obj.get('writing_mode') == 'vertical-rl' for page in manifest['pages'] for obj in page['objects']) == 3
        reopened = self.probe / f'{label}-reopened'
        result = subprocess.run([str(self.exe), str(saved), '--data-dir', str(self.data), '--smoke-dir', str(reopened)],
                                cwd=self.probe, env=self.env, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0 and digest(reopened / 'output.png') == actual[0], 'Saved installed-app project failed reopen/export'
        state_path = output / 'smoke-state.json'
        if state_path.exists():
            state = json.loads(state_path.read_text('utf-8'))
            presets = json.loads((self.data / 'presets.json').read_text('utf-8'))
            assert not state['presets_load_error']
            assert sorted(state['saved_style_names']) == sorted(presets['styles'])
            assert sorted(state['saved_layout_names']) == sorted(presets['layouts'])
            assert Path(state['data_dir']).resolve() == self.data.resolve(), 'Installed app used a different data directory'
            assert state['mutex_name'] == self.current['mutex_name'], 'Installed app used the production mutex during QA'
        elif label != 'previous-version':
            raise AssertionError('Current app must report loaded preset state for reinstall verification')
        self.assert_preserved()
        return {'pages_byte_identical': len(actual), 'saved_project_reopened': True, 'native_capture': str(output / 'window.png'),
                'presets_reloaded': state_path.exists()}

    def cancel_wizard(self):
        log = self.probe / 'wizard-cancel.log'
        process = subprocess.Popen([self.current['installer'], '/SP-', '/NORESTART', '/LANG=korean', f'/DIR={self.app_dir}', f'/LOG={log}'],
                                   cwd=self.probe, env=self.env)
        deadline, windows = time.monotonic() + 25, []
        while process.poll() is None and time.monotonic() < deadline:
            windows = self.native.windows(process.pid)
            if windows:
                break
            time.sleep(.1)
        assert windows, 'Installer wizard was not displayed'
        time.sleep(.5)
        windows = self.native.windows(process.pid)
        capture = self.probe / 'installer-wizard.png'
        self.native.capture(windows[0][0], capture)
        result = self.native.close(process, confirm=True)
        assert result == 2, f'Early cancellation should return 2, got {result}'
        assert not self.exe.exists() and registry_values(self.current['uninstall_key']) is None
        assert not self.group.exists()
        self.assert_preserved()
        self.checked('wizard_cancel_before_install_has_no_changes', {'exit_code': result, 'capture': str(capture)})

    def busy_application(self):
        before = digest(self.exe)
        registry_before = registry_values(self.current['uninstall_key'])
        shortcuts_before = self.shortcut_hashes()
        process = subprocess.Popen([str(self.exe), '--data-dir', str(self.data)], cwd=self.probe, env=self.env,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 25
        while process.poll() is None and time.monotonic() < deadline and not self.native.mutex_exists(self.current['mutex_name']):
            time.sleep(.1)
        assert process.poll() is None and self.native.mutex_exists(self.current['mutex_name']), 'Installed app did not acquire QA mutex'
        try:
            setup_code = self.run_setup(self.current, 'running-app-update-refused', expected_success=False,
                                        expected_reasons=('현재 실행 중임을 감지했습니다', 'application mutex is present'))
            assert process.poll() is None and digest(self.exe) == before, 'Setup changed or closed running app'
            self.assert_preserved()
            uninstall_code = self.uninstall('running-app-uninstall-refused', expected_success=False,
                                             expected_reasons='현재 실행 중임을 감지했습니다')
            assert process.poll() is None and digest(self.exe) == before, 'Uninstall changed or closed running app'
            assert registry_values(self.current['uninstall_key']) == registry_before
            assert self.shortcut_hashes() == shortcuts_before
            self.assert_preserved()
            self.checked('running_app_blocks_update_and_uninstall_without_forced_close',
                         {'setup_exit_code': setup_code, 'uninstall_exit_code': uninstall_code})
        finally:
            if process.poll() is None:
                assert self.native.close(process) == 0, 'Installed app did not exit cleanly'

    def execute(self):
        try:
            self.seed_user_data()
            self.cancel_wizard()
            code = self.run_setup(self.current, 'unsafe-data-folder-refused', destination=self.data, expected_success=False,
                                  expected_reasons='Translation Studio refused nonempty unowned installation directory')
            assert not (self.data / self.exe.name).exists() and not self.exe.exists()
            assert registry_values(self.current['uninstall_key']) is None and not self.group.exists()
            self.assert_preserved()
            self.checked('unsafe_install_folder_refused_without_changes', {'exit_code': code})
            self.run_setup(self.previous, 'install-previous')
            self.checked('previous_per_user_install', self.verify_registration(self.previous['version']))
            self.add_preserved(self.app_dir / '사용자가 추가한 작업.twproj', self.project)
            self.checked('seeded_valid_project_backup_presets_and_user_added_app_file', len(self.expected))
            self.checked('previous_installed_app_vertical_smoke', self.smoke('previous-version'))
            recent_before = digest(self.data / 'recent.json')
            old_exe_hash = digest(self.exe)
            self.run_setup(self.current, 'upgrade-current')
            assert digest(self.exe) != old_exe_hash, 'Upgrade did not replace previous executable'
            self.assert_preserved()
            assert digest(self.data / 'recent.json') == recent_before
            self.checked('upgrade_preserves_projects_backups_presets_and_recent', self.verify_registration(self.current['version']))
            self.checked('upgraded_installed_app_vertical_smoke', self.smoke('current-version'))
            current_exe_hash = digest(self.exe)
            registry_before = registry_values(self.current['uninstall_key'])
            shortcuts_before = self.shortcut_hashes()
            code = self.run_setup(self.previous, 'downgrade-refused', expected_success=False,
                                  expected_reasons='Translation Studio refused downgrade')
            assert digest(self.exe) == current_exe_hash and registry_values(self.current['uninstall_key']) == registry_before
            assert self.shortcut_hashes() == shortcuts_before
            self.assert_preserved()
            self.checked('downgrade_refused_without_changes', {'exit_code': code})
            alternative = self.probe / '다른 설치 위치' / 'Translation Studio'
            alternative.mkdir(parents=True)
            code = self.run_setup(self.current, 'update-directory-change-refused', destination=alternative, expected_success=False,
                                  expected_reasons='Translation Studio refused update to a different installation directory')
            assert not list(alternative.iterdir()), 'Refused update wrote into the new install directory'
            assert digest(self.exe) == current_exe_hash and registry_values(self.current['uninstall_key']) == registry_before
            assert self.shortcut_hashes() == shortcuts_before
            self.assert_preserved()
            self.checked('update_cannot_orphan_old_install_by_changing_directory', {'exit_code': code})
            self.busy_application()
            recent_before = digest(self.data / 'recent.json')
            self.uninstall('uninstall-current')
            self.assert_preserved()
            assert digest(self.data / 'recent.json') == recent_before
            self.checked('uninstall_removes_owned_payload_and_preserves_user_files')
            self.run_setup(self.current, 'reinstall-current')
            self.assert_preserved()
            assert digest(self.data / 'recent.json') == recent_before
            self.verify_registration(self.current['version'])
            self.checked('reinstall_recovers_saved_project_and_presets', self.smoke('reinstalled-version'))
            self.uninstall('final-qa-uninstall')
            self.assert_preserved()
            self.checked('qa_identity_and_shortcuts_removed_user_artifacts_retained')
            self.report['exit_code'] = 0
            self.report['system_only_path'] = True
            self.report['protected_user_files_sha256'] = self.expected
            self.write_report()
        except Exception as exc:
            self.report['exit_code'] = 1
            self.report['error'] = f'{type(exc).__name__}: {exc}'
            self.report['qa_registry_retained_for_diagnosis'] = registry_values(self.current['uninstall_key']) is not None
            self.write_report()
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous-metadata', type=Path, required=True)
    parser.add_argument('--current-metadata', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Native installer verification requires Windows')
    run = Verification(metadata(args.previous_metadata), metadata(args.current_metadata))
    run.execute()
    print('INSTALLER_RESULT=' + json.dumps(run.report, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
