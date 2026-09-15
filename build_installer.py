"""Wrap an immutable portable release in an isolated, reproducible Inno installer."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from prepare_installer import prepare, VERSION as COMPILER_VERSION
from studio import __version__
from studio.runtime import APP_ID, APP_MUTEX

ROOT = Path(__file__).resolve().parent


def build(app_source, version, qa_token=None):
    if not re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}', version):
        raise ValueError('버전은 숫자 세 부분으로 입력해 주세요.')
    if qa_token is not None and not re.fullmatch(r'[a-z0-9]{8,32}', qa_token):
        raise ValueError('QA 식별자가 올바르지 않습니다.')
    app_source = Path(app_source).resolve()
    # A build source must be an app we built, not an arbitrary directory tree.
    if not app_source.is_relative_to((ROOT / 'dist').resolve()) or app_source.name != 'Translation Studio':
        raise ValueError('dist 안의 이동식 배포 폴더를 선택해 주세요.')
    if not (app_source / 'Translation Studio.exe').is_file() or not (app_source / '_internal').is_dir():
        raise ValueError('완성된 이동식 배포본이 필요합니다.')
    if not qa_token:
        release = json.loads((app_source / 'release.json').read_text('utf-8'))
        if (release.get('version') != version or release.get('build_id') != app_source.parent.name or
                release.get('exe_sha256') != hashlib.sha256((app_source / 'Translation Studio.exe').read_bytes()).hexdigest()):
            raise ValueError('배포본 버전·실행 파일이 설치할 버전과 일치하지 않습니다. 이동식 배포본을 다시 빌드해 주세요.')
    forbidden = {'.twproj', '.bak', '.tmp'}
    files = list(app_source.rglob('*'))
    for path in files:
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(app_source):
            raise ValueError('배포본의 연결된 파일·폴더는 설치 파일에 포함할 수 없습니다.')
        if path.is_file() and (path.suffix.lower() in forbidden or path.name.lower() in {'presets.json', 'recent.json'}):
            raise ValueError('사용자 작업 파일을 설치 파일에 포함할 수 없습니다: ' + path.name)
    compiler = prepare()
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
    build_id = ('installer-qa-' if qa_token else 'installer-') + stamp
    output = ROOT / 'dist' / build_id
    stage = ROOT / '.build' / build_id / 'payload'
    output.mkdir(parents=True)
    shutil.copytree(app_source, stage)
    (stage / 'translation-studio.install.ini').write_text('', 'ascii')
    notice = stage / 'licenses' / 'Inno-Setup-LICENSE.txt'
    notice.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(compiler.parent / 'license.txt', notice)
    app_id = 'TranslationStudio.QA.' + qa_token if qa_token else APP_ID
    mutex = app_id + '.App' if qa_token else APP_MUTEX
    group = 'Translation Studio QA ' + qa_token if qa_token else 'Translation Studio'
    command = [str(compiler), '--quiet', '--define=AppVersion=' + version,
               '--define=BuildId=' + build_id, '--define=AppSource=' + str(stage),
               '--define=OutputDir=' + str(output)]
    if qa_token:
        command += ['--define=QAAppId=' + app_id, '--define=QAMutex=' + mutex, '--define=QAGroupName=' + group]
    command.append(str(ROOT / 'installer' / 'translation-studio.iss'))
    log_path = output / 'compiler.log'
    with log_path.open('wb') as stream:
        subprocess.run(command, check=True, stdout=stream, stderr=subprocess.STDOUT,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=900)
    installer = output / f'치pdf-{version}-Setup.exe'
    sha256 = hashlib.sha256(installer.read_bytes()).hexdigest()
    info = {'installer': str(installer), 'sha256': sha256, 'qa': bool(qa_token),
            'version': version, 'app_id': app_id, 'group_name': group, 'mutex_name': mutex,
            'uninstall_key': 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\' + app_id + '_is1',
            'build_id': build_id, 'source_release': str(app_source),
            'source_exe_sha256': hashlib.sha256((app_source / 'Translation Studio.exe').read_bytes()).hexdigest(),
            'compiler_version': COMPILER_VERSION, 'bytes': installer.stat().st_size}
    metadata = output / ('installer-qa.json' if qa_token else 'installer.json')
    metadata.write_text(json.dumps(info, ensure_ascii=False, indent=2), 'utf-8')
    (output / 'SHA256SUMS.txt').write_text(sha256 + '  ' + installer.name + '\n', 'utf-8')
    if not qa_token:
        (ROOT / 'latest-installer.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps({'metadata': str(metadata), **info}, ensure_ascii=True), flush=True)
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='검증된 이동식 배포본으로 설치 프로그램 생성')
    parser.add_argument('--app-source', type=Path)
    parser.add_argument('--version', default=__version__)
    parser.add_argument('--qa-token', help='별도 시험용 앱 등록·바로 가기 식별자')
    args = parser.parse_args()
    source = args.app_source or Path(json.loads((ROOT / 'latest-build.json').read_text('utf-8'))['exe']).parent
    if not args.qa_token and args.version != __version__:
        parser.error('프로덕션 설치 파일은 현재 앱 버전으로 빌드해야 합니다.')
    build(source, args.version, args.qa_token)
