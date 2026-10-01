# 실제 확인한 범위

## 통과

- Linux / Python 3.14.5 / Tk 8.6 / Xvfb 환경에서 **pytest 34개 통과**.
- 실제 Tk GUI 창 생성 및 종료 확인. 표시된 제목: `MapBuilder · 지역별 GraphML 생성기`.
- GUI 버튼 → spawn 자식 프로세스 → 합성 지도 분할/저장 → 완료 표시 확인.
- GUI 작업 취소 시 자식 종료·임시 파일 정리·버튼 복구 확인.
- GUI 실패 후 재시도 확인, 잘못된 입력 시 작업을 시작하지 않는지 확인.
- 한글 파일명, Windows 예약 파일명, 경로 구분자, 확장자 중복 처리 확인.
- 10/30/50m 간격, 곡선/역방향 geometry, 원래 좌표 끝점, 최대 간선 길이 확인.
- 기존 결과를 덮어쓰지 않으며 결과 폴더에 GraphML 파일 하나만 남는지 확인.
- 작업별 OSM 임시 캐시가 최종 폴더에 들어가지 않는지 확인.
- 실제 OSMnx의 단순화/투영/무방향 변환을 실행. 네트워크 다운로드/지역 검색만 합성 데이터로 대체.
- 너무 넓은 경계를 다운로드 전에 거부하는지 확인.
- requirements 순환 참조 및 API 서버 의존성이 없는지 확인.
- 새 출력 파일을 이전 `router.py` 로더로 읽고 480m 합성 Loop 생성 성공. 기존 스키마와 호환 확인.
- Linux에서 Windows 빌드 명령을 실행하면 명확히 중단하며 가짜 `.exe`를 생성하지 않는지 확인.

검증에 사용한 주요 라이브러리: OSMnx 2.1.1 / NetworkX 3.7 / Shapely 2.1.2 / pyproj 3.8.0. 검증 환경의 일부 GIS 파일 I/O 의존성은 없으므로, 전체 Windows 번들의 DLL 검증을 대신하는 결과는 아니다.

## 아직 확인하지 않은 범위

- **Windows EXE 빌드와 실제 Windows 실행**: Windows runner가 현재 연결되어 있지 않아 수행하지 못했다. EXE는 이 소스 ZIP에 포함되지 않는다.
- Windows one-file EXE의 전체 GIS DLL/PROJ/Tk/spawn 동작: `build_windows.py`가 빌드 후 실제 EXE로 검사하도록 구성했다. 아직 그 Windows 작업을 실행한 것은 아니다.
- 새 GUI를 통한 실제 지역 다운로드: 테스트는 OSM 서버를 호출하지 않았다.
- GitHub Actions workflow의 실제 실행: 사용자의 저장소에서 실행해야 한다.
- 코드 서명, SmartScreen 평판 및 여러 Windows 버전별 호환성.

**소스 기능 검증 성공과 Windows 실행 파일 검증 성공을 구분해야 한다.** 빌드 후 `dist/self-test-result.json`, `dist/gui-smoke-result.json`, `dist/build-info.json`이 성공으로 기록되었는지 확인한다.
