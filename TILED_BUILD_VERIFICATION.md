# 대형 지역 자동 타일 분할 검증 기록

## 구현 범위

- 일반 100km² 이하 단일 GraphML 생성은 기존대로 유지한다.
- 체크박스 `큰 지역 자동 타일 분할`을 선택하면 경계를 약 25km² 이하 core 타일로 나눈다.
- 각 core에 2km buffer를 더해 OSM 보행 그래프를 내려받고, 타일마다 `running-loop-v1` GraphML을 저장한다.
- `manifest.json`은 타일 파일명, core bbox, core/download 면적, 노드·간선 수와 바이트 수를 기록한다.
- 타일의 다운로드 영역이 100km²를 넘으면 더 잘게 분할한다.

## 자동 테스트

`tests/test_builder.py`에 다음 검사를 추가했다.

- 약 120km² 합성 경계가 복수 타일로 분할되는지
- 모든 타일의 buffer 포함 다운로드 면적이 100km² 이하인지
- overlap으로 download 면적이 core 면적보다 큰지
- 대형 타일 모드 job 옵션이 보존되는지

## 이 작업 환경에서 확인한 것

- `python -m py_compile builder_core.py map_builder.py map_processing.py`: 통과
- `new_job(..., tile_large_area=True)` 옵션·경로 생성: 통과

현재 작업 환경은 Python 3.14이며, MapBuilder는 Windows Python 3.12용 GIS wheel(GDAL/pyogrio)을 전제로 한다. 따라서 이 환경에서는 pyogrio의 GDAL 빌드 의존성이 없어 전체 GIS 테스트를 실행하지 못했다. Windows GitHub Actions 또는 Windows Python 3.12 빌드에서 `python -m pytest tests -q`와 EXE self-test를 실행해 최종 확인해야 한다. Windows EXE가 빌드·실행 검증된 것으로 주장하지 않는다.
