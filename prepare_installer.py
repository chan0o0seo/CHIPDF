"""Fetch the pinned, publisher-signed compiler into a project-local portable folder."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parent
VERSION = '7.1.0'
URL = 'https://github.com/jrsoftware/issrc/releases/download/is-7_1_0/innosetup-7.1.0-x64.exe'
SHA256 = '0362a383ed217d4c4239b5933866dd96d3eb2102737da92f80f6057a4b40df2f'
TOOL_ROOT = ROOT / '.build-tools' / ('inno-' + VERSION)
COMPILER = TOOL_ROOT / 'compiler' / 'ISCC.exe'


def prepare():
    if os.name != 'nt':
        raise RuntimeError('Windows에서 설치 프로그램을 빌드해 주세요.')
    TOOL_ROOT.mkdir(parents=True, exist_ok=True)
    installer = TOOL_ROOT / ('innosetup-' + VERSION + '-x64.exe')
    if not installer.exists():
        with urllib.request.urlopen(URL, timeout=60) as response:
            data = response.read(64_000_001)
        if len(data) > 64_000_000 or hashlib.sha256(data).hexdigest() != SHA256:
            raise ValueError('설치 제작 도구의 파일 해시가 고정된 버전과 다릅니다.')
        installer.write_bytes(data)
    if hashlib.sha256(installer.read_bytes()).hexdigest() != SHA256:
        raise ValueError('설치 제작 도구의 파일 해시가 올바르지 않습니다.')
    env = os.environ.copy()
    env['STUDIO_COMPILER_INSTALLER'] = str(installer)
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    # A Python child inherits PowerShell 7's module path verbatim, unlike a
    # directly launched Windows PowerShell 5 process. Use its own system modules.
    env['PSMODULEPATH'] = str(powershell.parent / 'Modules')
    result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command',
        "$s=Get-AuthenticodeSignature -LiteralPath $env:STUDIO_COMPILER_INSTALLER; "
        "if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notlike '*Pyrsys B.V.*') {exit 1}; exit 0"],
        env=env, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=60)
    if result.returncode:
        raise ValueError('설치 제작 도구의 배포자 서명을 확인하지 못했습니다.')
    if not COMPILER.exists():
        subprocess.run([str(installer), '/PORTABLE=1', '/CURRENTUSER', '/VERYSILENT',
            '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS', '/TASKS=', '/SP-',
            '/DIR=' + str(COMPILER.parent), '/LOG=' + str(TOOL_ROOT / 'bootstrap.log')],
            check=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=120)
    result = subprocess.run([str(COMPILER), '--version'], check=True, capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
    if VERSION not in result.stdout.decode('utf-8', 'replace'):
        raise ValueError('설치 제작 도구 버전이 맞지 않습니다.')
    record = {'version': VERSION, 'source': URL, 'sha256': SHA256,
              'publisher_signature': 'Valid: Pyrsys B.V.', 'portable_compiler': str(COMPILER)}
    (TOOL_ROOT / 'provenance.json').write_text(json.dumps(record, indent=2), 'utf-8')
    return COMPILER


if __name__ == '__main__':
    print(json.dumps({'compiler': str(prepare())}, ensure_ascii=True))
