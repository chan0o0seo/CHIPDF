# macOS 빌드 및 실행

macOS 15 이상을 대상으로 Apple Silicon(`arm64`)과 Intel(`x86_64`)용 앱을 별도로 빌드합니다. ` → 이 Mac에 관하여`에서 칩 종류를 확인하세요. 실행 파일의 지원 여부는 해당 커밋의 macOS builds 작업 결과에서 확인할 수 있습니다.

Windows EXE는 맥에서 직접 실행할 수 없습니다. 맥용 ZIP을 모두 풀어 `ChiPDF.app`을 응용 프로그램 폴더로 옮겨 실행하세요. 작업 파일 형식은 Windows와 같지만, 다른 운영체제에 없는 글꼴은 대체 글꼴로 표시되어 줄바꿈이 달라질 수 있습니다.

## 개발 환경

각 CPU 종류의 Mac에서 Python 3.12로 빌드합니다. Windows 빌드를 복사하거나 다른 CPU의 `.deps`를 재사용하지 마세요.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --only-binary=:all: -r requirements-dev.txt -r requirements-inpaint.txt
if [ "$(uname -m)" = "x86_64" ]; then
  brew install tesseract pkgconf
  python -m pip install Cython==3.1.6
  python -m pip install --no-cache-dir --force-reinstall --no-deps --no-binary=tesserocr --no-build-isolation tesserocr==2.10.0
fi
python prepare_assets.py
python prepare_inpaint.py --download
python main.py
```

OCR은 macOS용 tesserocr를 사용합니다. Intel용 wheel의 cysignals C API 불일치를 피하기 위해 Intel 개발 환경에서는 Homebrew의 Tesseract와 Cython으로 바인딩을 다시 빌드합니다. 배포 앱에는 필요한 실행 라이브러리를 함께 담습니다. 앱 데이터와 자동 저장본, 사용자 설정은 `~/Library/Application Support/TranslationStudio`에 보관합니다. Chrome는 `/Applications` 또는 `~/Applications`에 설치된 Google Chrome를 찾습니다. Chrome의 언어팩 준비와 번역 연결은 Windows 버전과 같은 방식입니다.

기본 한글 글꼴은 Apple SD Gothic Neo이며, 저장된 문서의 기존 글꼴 이름은 그대로 유지합니다. Qt가 저장·복사·붙여넣기 단축키의 Ctrl을 macOS의 Command로 처리합니다. Finder에서 앱으로 전달된 문서 열기 요청도 처리합니다.

## 패키징 및 검증

```sh
python -m unittest test_platform_support test_recent_files test_studio test_text_mask test_inpaint_engine
python build_macos.py --with-inpaint
python verify_macos.py
```

`dist/macos-*/`에 `.app`, CPU 종류별 ZIP, SHA256 목록을 만듭니다. LaMa 모델과 OCR·PDF 실행 라이브러리를 포함하며, 사용자의 Homebrew/Python 설치에 의존하지 않는 실행을 검증합니다. 검증은 한글 경로에서 앱 시작, PNG·PDF 출력, 최근 작업, 두 일본어 OCR 모델 초기화와 LaMa CPU 추론·선택 영역 밖 픽셀 보존을 포함합니다. Chrome 실제 번역, 한글 입력기 조합, 다양한 사진의 복원 품질은 별도 사용자 검증이 필요합니다.

GitHub Actions의 `macOS builds`가 두 CPU용 앱을 빌드하고 검증에 성공한 ZIP을 작업 아티팩트로 제공합니다. Apple Developer 배포 인증서와 공증 자격 증명은 설정되어 있지 않으므로 현재 빌드는 **임시 서명(ad-hoc)이며 Apple 공증을 받지 않았습니다**. 다운로드한 앱은 macOS에서 실행 확인을 요구하거나 차단할 수 있습니다. 일반 배포용 서명·공증은 별도 설정이 필요합니다.

참고: [PyInstaller macOS 패키징](https://pyinstaller.org/en/stable/feature-notes.html#macos-multi-arch-support), [Qt 단축키](https://doc.qt.io/qt-6/qkeysequence.html), [tesserocr 설치](https://github.com/sirfz/tesserocr#installation).
