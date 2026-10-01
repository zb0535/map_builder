# MapBuilder — 지역명으로 GraphML을 만드는 독립 프로그램

**이 패키지가 이전 `loop-routing` / `map-builder.zip` 대신 사용할 지도 생성기 소스입니다.**

FastAPI, API 서버, 코스 추천, Render 실행 파일은 포함하지 않습니다. 원하는 지역을 입력해서 GraphML 데이터만 만드는 프로그램입니다.

> **현재 전달물은 소스 + Windows EXE 자동 빌드 구성입니다. 완성된 EXE가 동봉된 것은 아닙니다.**
> 작성 환경이 Linux이므로 Windows EXE를 생성하거나 Windows에서 실행 검증하지 못했습니다.
> 아래 A 또는 B 방법으로 Windows에서 빌드하면 `dist/MapBuilder.exe`가 만들어집니다.

## 1. 완성된 EXE 사용법 (사용자 PC에 Python 불필요)

1. `MapBuilder.exe`를 실행합니다.
2. 지역명을 입력합니다. 예: `광주광역시 북구 용봉동` 또는 `서울특별시 영등포구 여의도동`.
3. 결과를 저장할 폴더를 선택합니다.
4. 파일 이름은 선택 사항입니다. 비우면 지역명을 사용합니다.
5. 최대 간선 길이를 정합니다. 기본 50m, 범위 10~50m.
6. **지도 생성**을 누릅니다. 인터넷과 OSM 서버 상태에 따라 수 분 이상 걸릴 수 있습니다.
7. 완료되면 **결과 폴더 열기**를 누릅니다.

출력 예:

```text
선택한_저장폴더/
└── 광주광역시_북구_용봉동_20261001_130000_a1b2c3d4/
    └── 광주광역시_북구_용봉동.graphml
```

**결과 폴더에는 GraphML 파일 하나만 들어갑니다.** 임시 OSM 응답 캐시는 결과에 넣지 않습니다. 날짜/식별자를 붙여 이전 결과를 덮어쓰지 않습니다.

기존 파일명처럼 만들고 싶다면 파일 이름 칸에 `yongbong_map`을 입력하세요. 확장자는 자동으로 붙습니다.

이후 다른 프로젝트에는 `.graphml`만 복사해서 사용하면 됩니다. 생성기 EXE, Python, OSMnx를 실행 서버에 옮길 필요가 없습니다. 단, GraphML 자체가 프로그램은 아니므로 이를 읽는 기존 프로젝트의 로더/경로 탐색 코드는 필요합니다.

## 2. EXE 만들기 — 아래 중 하나만 선택

### A. Windows PC에서 한 번 빌드

빌드하는 PC에만 **Python 3.12 x64**가 필요합니다. Python 공식 설치 프로그램의 기본 Tcl/Tk 및 Python Launcher 구성요소를 포함하세요.

1. 압축을 풉니다.
2. `build_exe.bat`을 더블클릭합니다.
3. 전용 `.build-venv`에 의존성을 설치하고, EXE를 만들고, 그 EXE를 자동 검사합니다.
4. 성공 메시지가 나오면 `dist/MapBuilder.exe`를 사용하거나 다른 Windows PC로 복사합니다.

명령줄에서도 가능합니다:

```powershell
cd map-builder-desktop
py -3.12 build_windows.py
```

- 빌드 PC와 **빌드된 EXE 실행 PC**를 구분하세요. 실행 PC에는 Python 설치가 필요 없습니다.
- `.bat` 자체가 완성 프로그램은 아닙니다. EXE를 **생성하는 빌드 명령**입니다.
- 처음 설치/빌드할 때 인터넷이 필요합니다.
- GIS 라이브러리와 Python/Tk를 포함하므로 EXE가 크고, 최초 실행 시 압축 해제로 잠시 걸릴 수 있습니다.
- Windows x64용입니다. macOS/Linux 실행 파일이 아닙니다. Linux에서 확장자만 `.exe`로 바꾸지 않습니다.

### B. 내 PC에 Python 설치 없이 GitHub Actions에서 빌드

1. 본인이 관리하는 GitHub 저장소를 준비합니다.
2. **이 폴더 자체가 아니라 폴더 안의 내용**을 저장소 루트에 넣습니다. 숨김 폴더 `.github`도 반드시 포함합니다.
3. GitHub의 **Actions → Build Windows EXE → Run workflow**를 실행합니다.
4. 빌드와 자동 검사가 성공하면 해당 실행의 **Artifacts → MapBuilder-Windows-x64**를 다운로드합니다.
5. 압축 안의 `MapBuilder.exe`를 실행합니다.

필요한 저장소 구조:

```text
.github/workflows/windows-exe.yml
map_builder.py
builder_core.py
map_processing.py
self_test.py
runtime_hook.py
MapBuilder.spec
build_windows.py
requirements.txt
requirements-build.txt
```

이 방법도 실제 빌드는 GitHub의 Windows runner에서 수행합니다. 여기서 대신 저장소를 생성하거나 workflow를 실행한 것은 아닙니다. GitHub 계정의 Actions 정책/사용량에 따라 실행 가능 여부나 비용이 달라질 수 있습니다.

## 3. 빌드 검증 장치

`build_windows.py`는 다음을 모두 통과해야 성공으로 처리합니다.

- Windows x64 PE 실행 파일인지 확인.
- 만들어진 **EXE 자체**로 `--self-test` 실행.
- OSMnx/GeoPandas/pyogrio(GDAL)/Shapely/pyproj(PROJ)/NumPy 등의 import 확인.
- 좌표계 변환 → 50m 분할 → 한글 경로에 저장 → GraphML 다시 읽기.
- frozen EXE의 별도 프로세스(spawn) 실행 확인.
- 실제 Tk GUI 창 생성/종료 확인.
- 결과 JSON, 빌드 의존성 버전, EXE SHA-256 기록.

검사 실패 시 실행 파일을 `MapBuilder.failed-build`로 바꾸며, GitHub Actions에서도 성공 배포물로 올리지 않습니다. **이 자동 검사는 인터넷을 호출하지 않습니다.** 실제 지역 다운로드는 OSM 서버 상태에 영향을 받으므로 별도 현장 확인이 필요합니다.

## 4. 지도 처리 방식과 범위

- 지역명으로 행정구역 Polygon을 찾습니다. 경계가 검색되지 않으면 실패 메시지를 표시합니다.
- 과도한 메모리/다운로드를 방지하기 위해 경계 면적을 **100km² 이하**로 제한합니다. 동/읍/면 단위를 권장합니다.
- OSM 보행 네트워크(`walk`)의 주 연결 성분을 사용합니다. 지역 내 모든 고립된 도로까지 보장하지는 않습니다.
- 횡단 관련 태그를 보존하며 단순화하고, 미터 단위 좌표계로 투영합니다.
- 왕복 방향으로 표현된 같은 도로를 무방향 간선으로 정리한 후 분할합니다.
- 원래 도로 곡선을 보존하며 길이를 최대 설정값 이하로 나눕니다.
- 가상 노드는 음수 ID를 사용하고 기존 OSM 노드는 유지합니다.
- 출력 스키마는 기존 용봉동 파일과 같은 **`running-loop-v1`**입니다. 일반 OSMnx 원본 GraphML과 속성 구성이 다릅니다.
- 구간 길이와 횡단 관련 태그는 포함하지만 고도·그늘 데이터는 자동 생성하지 않습니다.
- 다른 프로젝트에서는 `networkx.read_graphml()`이나 해당 스키마용 로더로 읽을 수 있습니다. 기존 로더에 파일 경로를 지정하세요.

다운로드는 별도 프로세스에서 실행되므로 창이 멈추지 않습니다. **취소**를 누르면 작업을 종료하고 작업 전용 임시 폴더를 정리합니다. 완료 직후 취소했다면 이미 완성된 GraphML은 삭제하지 않습니다. 프로세스 강제 종료/PC 전원 차단 시에는 저장 위치에 `.mapbuilder-*` 임시 폴더가 남을 수 있습니다. 작업이 실행 중이 아님을 확인한 뒤 그 임시 폴더만 정리하면 됩니다.

## 5. 오류가 나는 경우

- **지역 경계를 찾을 수 없음:** `시/도 + 구 + 동/읍/면`까지 구체적으로 입력합니다.
- **영역이 너무 큼:** 더 작은 지역명을 입력합니다.
- **다운로드/통신 실패:** 네트워크·방화벽을 확인하고 잠시 후 재시도합니다. 다른 서비스로 몰래 바꾸거나 가상 지도를 실제 지도처럼 저장하지 않습니다.
- **저장 권한 없음:** Documents 등 본인 계정이 쓸 수 있는 저장 폴더를 선택합니다.
- **Windows 긴 경로 오류:** 저장 위치를 짧게 하고 파일 이름 칸에 짧은 이름을 지정합니다.
- **빌드 실패:** `build_exe.bat` 창에 나타나는 오류와 `dist/self-test-result.json`을 확인합니다. 생성/검사에 실패한 파일은 사용하지 않습니다.
- **SmartScreen 등 보안 경고:** 개인 빌드 EXE에는 코드 서명이 없습니다. 출처·소스·SHA-256 및 조직의 보안 정책을 확인하세요. 보안 프로그램을 끄는 방식으로 해결하지 마세요.

## 6. 개발 실행·테스트

소스 상태에서 실행할 때만 Python과 의존성 설치가 필요합니다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python map_builder.py
.\.venv\Scripts\python -m pip install pytest
.\.venv\Scripts\python -m pytest tests -q
```

테스트는 합성 입력으로 저장·분할·취소·오류 처리를 확인합니다. OSM 서버에 요청하지 않습니다. 실제 Tk GUI 검사는 화면 환경이 필요하며, Linux에서는 Xvfb를 사용할 수 있습니다. 작성 환경에서 확인한 범위는 `VERIFICATION.md`를 참고하세요.

## 데이터 및 배포 주의

지도 데이터는 © OpenStreetMap contributors이며 ODbL 이용 조건을 확인해야 합니다. 실제 도로의 개방 여부·공사·안전성을 보장하지 않습니다. 외부에 EXE를 배포할 때는 포함된 Python 및 GIS 의존성의 라이선스/고지 조건도 확인하세요.
