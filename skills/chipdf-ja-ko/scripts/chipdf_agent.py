"""Locate ChiPDF and call its bundled automation engine. Standard library only."""
from __future__ import annotations

import argparse
import configparser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROTOCOL = 'chipdf-ja-ko/1'
EXE_NAMES = ('Translation Studio.exe', 'ChiPDF.exe', 'chipdf.exe')
APP_ID = '3A2EF1A7-51E4-4D2F-8121-F1C5EDE795AC'


def connection_file():
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA', str(Path.home())))
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support'
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
    return base / 'ChiPDF' / 'agent-connection.json'


def executables_at(path):
    path = Path(path).expanduser()
    if path.suffix.lower() == '.app':
        for name in ('ChiPDF', 'Translation Studio'):
            yield path / 'Contents/MacOS' / name
    elif path.is_dir():
        for name in EXE_NAMES:
            yield path / name
    else:
        yield path


def remembered_executables(config_path):
    try:
        config = json.loads(config_path.read_text(encoding='utf-8'))
        if isinstance(config.get('executable'), str):
            yield from executables_at(config['executable'])
    except (OSError, ValueError, AttributeError):
        pass


def installation_locations():
    """The installer records its final location next to the copied user skill."""
    config = configparser.ConfigParser(interpolation=None)
    try:
        data = (Path(__file__).resolve().parents[1] / 'chipdf-install.ini').read_bytes()
        encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
        config.read_string(data.decode(encoding))
        executable = config.get('ChiPDF', 'Executable', fallback='').strip()
        if executable and Path(executable).is_absolute():
            yield Path(executable)
    except (OSError, UnicodeError, configparser.Error):
        pass


def nearby_executables(folder):
    """Inspect one portable folder or a development build manifest, without scanning."""
    if folder.suffix.lower() == '.app':
        yield from executables_at(folder)
    for name in EXE_NAMES:
        yield folder / name
    try:
        manifest = json.loads((folder / 'latest-build.json').read_text(encoding='utf-8-sig'))
        executable = Path(manifest['exe'])
        yield executable if executable.is_absolute() else folder / executable
    except (OSError, ValueError, KeyError, TypeError):
        pass


def registry_locations():
    if sys.platform != 'win32':
        return
    import winreg
    prefix = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\'
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            for identity in (APP_ID, '{' + APP_ID + '}'):
                try:
                    with winreg.OpenKey(hive, prefix + identity + '_is1', 0, winreg.KEY_READ | view) as key:
                        for value_name in ('InstallLocation', 'Inno Setup: App Path'):
                            try:
                                location = winreg.QueryValueEx(key, value_name)[0]
                                if isinstance(location, str) and location.strip():
                                    yield Path(location)
                            except OSError:
                                continue
                except OSError:
                    continue


def candidates(explicit=None):
    if explicit:
        yield from executables_at(explicit)
        return
    if os.environ.get('CHIPDF_EXE'):
        yield from executables_at(os.environ['CHIPDF_EXE'])
    yield from remembered_executables(connection_file())
    yield from installation_locations()
    # Windows app sandboxes can redirect LOCALAPPDATA to a per-session folder.
    # Also read the host user's saved connection and default installation.
    if sys.platform == 'win32' and os.environ.get('USERPROFILE'):
        host_config = Path(os.environ['USERPROFILE']) / 'AppData/Local/ChiPDF/agent-connection.json'
        if host_config != connection_file():
            yield from remembered_executables(host_config)
    yield from (exe for location in registry_locations() for exe in executables_at(location))
    if sys.platform == 'win32':
        for variable in ('LOCALAPPDATA', 'USERPROFILE', 'ProgramFiles', 'ProgramFiles(x86)'):
            if os.environ.get(variable):
                base = Path(os.environ[variable])
                if variable == 'LOCALAPPDATA':
                    base /= 'Programs'
                elif variable == 'USERPROFILE':
                    base /= 'AppData/Local/Programs'
                for folder in ('Translation Studio', 'ChiPDF'):
                    yield from executables_at(base / folder)
    elif sys.platform == 'darwin':
        for base in (Path('/Applications'), Path.home() / 'Applications'):
            yield from executables_at(base / 'ChiPDF.app')
    for name in (*EXE_NAMES, 'chipdf', 'ChiPDF'):
        found = shutil.which(name)
        if found:
            yield Path(found)
    # A copied user skill loses its adjacency to a portable app. Its working
    # directory can still be the app folder or contain our build manifest.
    for folder in (Path.cwd(), *Path(__file__).resolve().parents):
        yield from nearby_executables(folder)


def communication_parent():
    if sys.platform == 'win32' and os.environ.get('USERPROFILE') and os.environ.get('LOCALAPPDATA'):
        local = Path(os.environ['LOCALAPPDATA'])
        packages = Path(os.environ['USERPROFILE']) / 'AppData/Local/Packages'
        if local.name.upper() == 'AC' and local.is_relative_to(packages):
            # A desktop executable launched from an app sandbox cannot share
            # its private TEMP folder. The task working folder is shared.
            return Path.cwd()
    return None


def invoke(command, arguments, timeout):
    with tempfile.TemporaryDirectory(prefix='chipdf-agent-', dir=communication_parent()) as temp:
        result_path = Path(temp) / 'result.json'
        result = subprocess.run([*command, '--agent', '--result-json', str(result_path), *arguments],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                                timeout=timeout)
        if not result_path.is_file():
            detail = result.stderr.decode('utf-8', errors='replace').strip()[-1200:]
            raise RuntimeError('ChiPDF did not return automation JSON. Check automation support and execution permissions.' +
                               (f' {detail}' if detail else ''))
        data = json.loads(result_path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise RuntimeError('ChiPDF returned an invalid automation response.')
        if result.returncode or 'error' in data:
            raise RuntimeError(data.get('error', f'ChiPDF exited with code {result.returncode}.'))
        return data


def resolve_command(args):
    if args.chipdf_root:
        root = args.chipdf_root.resolve()
        if not (root / 'studio/agent_cli.py').is_file():
            raise ValueError('This source directory does not support ChiPDF automation.')
        command = [sys.executable, str(root / 'main.py')]
        info = invoke(command, ['info'], 20)
        return command, info
    checked, incompatible = set(), []
    for candidate in candidates(args.exe):
        candidate = candidate.resolve()
        if candidate in checked or not candidate.is_file():
            continue
        checked.add(candidate)
        try:
            info = invoke([str(candidate)], ['info'], 20)
            if info.get('app') != 'ChiPDF' or info.get('protocol') != PROTOCOL:
                raise RuntimeError('Unsupported automation protocol. Update ChiPDF to an automation-enabled build.')
            return [str(candidate)], info
        except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
            incompatible.append(f'{candidate}: {exc}')
    if incompatible:
        raise RuntimeError('Found ChiPDF, but could not connect to its automation engine.\n' +
                           '\n'.join(incompatible))
    raise FileNotFoundError('ChiPDF was not found. Install an automation-enabled ChiPDF build, '
                            'or supply --exe <path> --remember for a portable installation.')


def edit_project(command, arguments):
    """Start the normal editor, optionally on a separate finishing copy."""
    parser = argparse.ArgumentParser(prog='chipdf_agent.py edit')
    parser.add_argument('project', type=Path)
    parser.add_argument('--output', type=Path, help='Create a new editing copy; existing files are never replaced.')
    args = parser.parse_args(arguments)
    project = args.project.expanduser().resolve()
    if project.suffix.lower() != '.twproj' or not project.is_file():
        raise ValueError(f'Choose an existing .twproj project: {project}')
    destination = args.output.expanduser().resolve() if args.output else project
    if destination.suffix.lower() != '.twproj':
        raise ValueError('The editing copy must use the .twproj extension.')
    if args.output:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also rejects --output pointing back to the source.
        with destination.open('xb') as target:
            try:
                with project.open('rb') as source:
                    shutil.copyfileobj(source, target)
            except Exception:
                target.close()
                destination.unlink()
                raise
    environment = os.environ.copy()
    if environment.get('QT_QPA_PLATFORM') in ('offscreen', 'minimal'):
        environment.pop('QT_QPA_PLATFORM')
    options = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL,
               'stderr': subprocess.DEVNULL, 'env': environment, 'close_fds': True}
    if sys.platform == 'win32':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options['start_new_session'] = True
    process = subprocess.Popen([*command, str(destination)], **options)
    return {'project': str(destination), 'source_project': str(project),
            'status': 'editor_launched', 'pid': process.pid,
            'next': 'Save the project in ChiPDF, then run preview/export on this saved project.'}


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__,
        epilog='Commands: info, prepare, apply, preview, export, edit. edit opens the desktop editor.')
    parser.add_argument('--exe', type=Path, help='Explicit executable, installation directory, or .app bundle.')
    parser.add_argument('--remember', action='store_true', help='Remember a verified executable for subsequent calls.')
    parser.add_argument('--chipdf-root', type=Path, help='Optional source development fallback; not needed for installed builds.')
    parser.add_argument('--timeout', type=float, default=1800, help='Execution timeout in seconds.')
    args, remaining = parser.parse_known_args(argv)
    try:
        if args.timeout <= 0 or args.timeout == float('inf') or args.timeout != args.timeout:
            raise ValueError('--timeout must be positive and finite.')
        if '--result-json' in remaining:
            raise ValueError('--result-json is reserved for launcher communication.')
        command, info = resolve_command(args)
        if args.remember:
            if args.chipdf_root:
                raise ValueError('--remember is for executable installations, not source directories.')
            config_path = connection_file()
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=config_path.parent,
                                             delete=False, suffix='.tmp') as handle:
                json.dump({'executable': command[0]}, handle, ensure_ascii=False)
                temp_path = Path(handle.name)
            try:
                os.replace(temp_path, config_path)
            finally:
                temp_path.unlink(missing_ok=True)
        result = {**info, 'executable': command[0], 'mode': 'source' if args.chipdf_root else 'installed'}
        result['launcher_commands'] = ['edit']
        if remaining[:1] == ['edit']:
            result = edit_project(command, remaining[1:])
        elif remaining and remaining != ['info']:
            if args.chipdf_root:
                remaining = ['--chipdf-root', str(args.chipdf_root.resolve()), *remaining]
            result = invoke(command, remaining, args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
