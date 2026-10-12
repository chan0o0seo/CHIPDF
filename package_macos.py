"""Combine the two native Mac builds into one downloadable release ZIP."""
import argparse
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

from studio import __version__


def package(artifacts, output):
    if sys.platform != 'darwin':
        raise RuntimeError('macOS의 ditto로 앱 권한과 심볼릭 링크를 보존해 패키징하세요.')
    artifacts, output = Path(artifacts).resolve(), Path(output).resolve()
    archives = list(artifacts.rglob('*.zip'))
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f'chipdf-{__version__}.zip'
    with tempfile.TemporaryDirectory(prefix='chipdf-macos-') as directory:
        bundle = Path(directory) / f'chipdf-{__version__}'
        bundle.mkdir()
        for arch, folder in [('arm64', 'Apple-Silicon'), ('x86_64', 'Intel')]:
            matches = [path for path in archives if f'-{arch}' in path.name]
            if len(matches) != 1:
                raise ValueError(f'{arch} 빌드 ZIP이 하나 필요합니다: {matches}')
            destination = bundle / folder
            destination.mkdir()
            subprocess.run(['ditto', '-x', '-k', str(matches[0]), str(destination)], check=True)
            app = destination / 'ChiPDF.app'
            with (app / 'Contents/Info.plist').open('rb') as stream:
                info = plistlib.load(stream)
            if info['CFBundleShortVersionString'] != __version__:
                raise ValueError(f'{arch} 앱 버전이 {__version__}과 다릅니다.')
            architecture = subprocess.check_output(
                ['lipo', '-archs', str(app / 'Contents/MacOS/ChiPDF')], text=True).split()
            if arch not in architecture:
                raise ValueError(f'{arch} 앱의 실행 파일 아키텍처가 다릅니다: {architecture}')
        shutil.copy2(Path(__file__).resolve().parent / 'docs/mac-install.txt', bundle / '설치 안내.txt')
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
                        str(bundle), str(archive)], check=True)
    print(json.dumps({'version': __version__, 'zip': str(archive), 'bytes': archive.stat().st_size}))
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Apple Silicon·Intel용 치pdf를 단일 ZIP으로 묶기')
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    package(args.artifacts, args.output)
