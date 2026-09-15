# Windows 10 호환성 수정 · 0.7.1

0.7.0 설치 프로그램은 `MinVersion=10.0.22000`으로 Windows 11만 허용했다. 0.7.1에서는 Windows 10 버전 1809(빌드 17763) 이상을 허용하도록 `MinVersion=10.0.17763`으로 수정한다. 64비트 x64 배포이며 Windows 10 32비트나 1809 이전 버전은 대상이 아니다. 기존 AppId·작업 저장 위치·프로젝트 버전 6 형식은 유지한다.

## 호환성 근거

- 포함된 Qt 6.10.2의 공식 지원 범위에 Windows 10 1809 이상 x86_64가 포함된다. [Qt 6.10 지원 플랫폼](https://doc.qt.io/qt-6.10/supported-platforms.html)
- 포함된 Python 3.12는 Windows 8.1 이상을 지원한다. 사용자는 Python을 별도로 설치하지 않는다. [Python 3.12 Windows 문서](https://docs.python.org/3.12/using/windows.html)
- Qt6Core는 운영체제의 `icuuc.dll`을 사용한다. 이 DLL은 Windows 10 1703부터 제공된다. 개발 PC의 Poppler ICU DLL을 패키지에 섞지 않는 빌드 경로 격리를 유지한다. [Microsoft ICU 문서](https://learn.microsoft.com/en-us/windows/win32/intl/international-components-for-unicode--icu-)
- Inno Setup은 Windows 10 설치를 지원하며 `MinVersion`이 지정한 빌드 미만에서 설치를 거절한다. [Inno Setup 지원 환경](https://jrsoftware.org/isinfo.php), [MinVersion](https://jrsoftware.org/ishelp/topic_setup_minversion.htm)
- 실행 파일, Python, Qt, PDFium, OCR·번역 모듈의 PE 헤더와 정적 가져오기 정보를 확인했다. 검토한 모듈에서 Windows 11 전용의 필수 API는 발견하지 못했다. 이 정적 검토는 모든 지연 로딩·드라이버·하드웨어 환경에서의 실행 보장을 의미하지 않는다.

## 검증 범위

개발·실행 검증 PC는 Windows 11이다. 새 배포본은 프로젝트 재열기·PNG/PDF 출력·OCR·로컬 번역 회귀, 설치·업데이트·제거·재설치 시 작업 보존을 같은 PC의 격리된 시험 폴더에서 확인한다. `qa/portable-result.json`, `qa/installer-result.json`, `qa/tests-071.log`, `qa/release-071.json`이 해당 실행 결과의 기준이다. `qa/win10-native-imports.json`은 변경 전 배포본의 정적 가져오기 조사 자료이며, `qa/win10-compatibility-071.json`에는 새 0.7.1 바이너리의 해시·PE 헤더·가져오기 정보를 별도로 기록했다. 조사한 모듈의 가져오기 API는 이전 배포본과 같고 Python 버전은 양쪽 모두 3.12.14다.

2026-09-14 전체 113개 테스트와 실제 설치 순환의 13개 검사가 통과했다. `qa/install-8cba3626d8`에서 0.7.0→0.7.1 업데이트와 제거·재설치, 작업·복구·백업·서식 5개 파일의 바이트 보존을 확인했다. 배포본 회귀 검증도 통과했으며 세로쓰기 카드 3장과 작품 27페이지의 PNG가 이전 결과와 일치했다. 최종 파일은 `dist/installer-20260914-094811-f2af1e/Translation-Studio-0.7.1-Setup.exe`이며 SHA-256과 검증 범위는 옆의 `verification.json`에 기록한다.

Windows 10 실기 또는 Windows 10 가상 머신에서의 실제 실행은 아직 검증하지 않았다. OS 버전 위장이나 호환성 모드를 실제 Windows 10 시험으로 취급하지 않는다. Windows 10에서 최초 실행, PDF·이미지 열기, 한글 입력, OCR·번역, 저장·재열기·출력과 제거를 추가 확인해야 한다.
