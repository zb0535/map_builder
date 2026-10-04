"""GUI 없이도 검사 가능한 작업 관리. FastAPI/라우팅 서버는 포함하지 않는다."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shutil
import traceback
import unicodedata
import uuid
import xml.etree.ElementTree as ET

MAX_AREA_KM2 = 100.0  # 단일 파일 안전 한도
TILE_CORE_AREA_KM2 = 25.0  # 2km 겹침 버퍼를 더해도 타일 다운로드가 안전 한도 안에 남도록 보수적으로 설정
TILE_OVERLAP_KM = 2.0


def safe_stem(text: str) -> str:
    """Windows에서 사용할 수 있는 파일/폴더 이름. 경로 입력으로 탈출할 수 없게 한다."""
    name = unicodedata.normalize("NFKC", text.strip())
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", "_", name).strip(" ._")[:70].rstrip(" .")
    if not name:
        name = "map"
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "map_" + name
    return name


def new_job(place: str, output_parent: str | Path, name: str = "", max_segment_m: float = 50,
            tile_large_area: bool = False) -> dict:
    place = place.strip()
    if not 2 <= len(place) <= 200:
        raise ValueError("지역명을 2~200자로 입력하세요. 예: 광주광역시 북구 용봉동")
    try:
        segment = float(max_segment_m)
    except (TypeError, ValueError) as exc:
        raise ValueError("분할 간격은 10~50 사이의 숫자로 입력하세요.") from exc
    if not math.isfinite(segment) or not 10 <= segment <= 50:
        raise ValueError("분할 간격은 10~50m 사이로 입력하세요.")
    if not str(output_parent).strip():
        raise ValueError("저장 폴더를 선택하세요.")
    parent = Path(output_parent).expanduser().resolve()
    if not parent.is_dir():
        raise ValueError("존재하는 저장 폴더를 선택하세요.")
    chosen = name.strip() or place
    if chosen.lower().endswith(".graphml"):
        chosen = chosen[:-len(".graphml")]
    stem = safe_stem(chosen)
    token = uuid.uuid4().hex[:8]
    # 기존 결과를 덮어쓰지 않도록 매 작업마다 새로운 폴더를 만든다.
    final = parent / f"{stem}_{datetime.now():%Y%m%d_%H%M%S}_{token}"
    stage = parent / f".mapbuilder-{token}"
    return {"place": place, "stem": stem, "max_segment_m": segment,
            "parent": str(parent), "stage": str(stage), "final": str(final),
            "filename": f"{stem}.graphml", "tile_large_area": bool(tile_large_area),
            "tile_core_area_km2": TILE_CORE_AREA_KM2, "tile_overlap_km": TILE_OVERLAP_KM}


def _configure_osmnx(job: dict):
    """대형 타일 작업도 같은 캐시·횡단보도 설정을 사용한다."""
    import osmnx as ox
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(Path(job["stage"]) / ".osm-cache")
    ox.settings.log_console = False
    ox.settings.log_file = False
    ox.settings.requests_timeout = 120
    ox.settings.useful_tags_node = list(dict.fromkeys(
        list(ox.settings.useful_tags_node) + ["highway", "crossing", "crossing:signals"]
    ))
    return ox


def _download_polygon(ox, polygon, notify) -> object:
    notify("OSM 보행로 다운로드 중… 통신 상황에 따라 수 분 걸릴 수 있습니다.")
    raw = ox.graph_from_polygon(polygon, network_type="walk", simplify=False, retain_all=False)
    notify("횡단 노드 보존 및 도로 단순화 중…")
    simple = ox.simplification.simplify_graph(raw, node_attrs_include=["highway", "crossing"])
    del raw
    notify("미터 좌표계 변환 및 양방향 도로 통합 중…")
    projected = ox.project_graph(simple)
    del simple
    return ox.convert.to_undirected(projected)


def _resolve_boundary(job: dict, notify):
    ox = _configure_osmnx(job)
    notify(f"지역 경계 검색: {job['place']}")
    boundary = ox.geocode_to_gdf(job["place"])
    polygon = boundary.geometry.iloc[0]
    if polygon.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("행정구역 경계를 찾지 못했습니다. 시/구/동을 함께 입력하세요.")
    area_km2 = float(ox.projection.project_gdf(boundary).geometry.area.sum()) / 1_000_000
    if not math.isfinite(area_km2) or area_km2 <= 0:
        raise ValueError("검색 영역 면적을 계산할 수 없습니다.")
    return ox, boundary, polygon, area_km2, str(boundary.iloc[0].get("display_name", job["place"]))


def download_projected(job: dict, notify) -> tuple:
    # GUI 시작은 가볍게, 큰 GIS 라이브러리는 자식 프로세스에서만 import한다.
    notify("지도 라이브러리 준비 중… 처음에는 잠시 걸릴 수 있습니다.")
    ox, _boundary, polygon, area_km2, display_name = _resolve_boundary(job, notify)
    if area_km2 > MAX_AREA_KM2:
        raise ValueError(f"검색 영역이 {area_km2:,.1f}km²입니다. {MAX_AREA_KM2:g}km² 이하의 동/읍/면 단위 지역을 지정하거나 ‘큰 지역 자동 타일 분할’을 선택하세요.")
    notify(f"확인된 지역: {display_name} ({area_km2:.2f}km²)")
    return _download_polygon(ox, polygon, notify), display_name


def plan_large_area_tiles(boundary, *, core_area_km2: float = TILE_CORE_AREA_KM2,
                          overlap_km: float = TILE_OVERLAP_KM) -> list[dict]:
    """경계 내부 core와 검색용 overlap 영역을 가진 타일 계획을 만든다.

    GraphML에는 overlap 도로도 저장한다. 그래야 타일 경계 근처 사용자도 닫힌 Loop를 찾을 수 있다.
    manifest의 core_bbox는 나중에 런타임이 담당 타일을 고를 때 사용한다.
    """
    import geopandas as gpd
    from shapely.geometry import box

    if not 0 < core_area_km2 < MAX_AREA_KM2 or not 0 < overlap_km <= 5:
        raise ValueError("타일 면적 또는 겹침 버퍼 설정이 잘못됐습니다.")
    metric = boundary.to_crs(boundary.estimate_utm_crs())
    region = metric.geometry.unary_union
    min_x, min_y, max_x, max_y = region.bounds
    width, height = max_x - min_x, max_y - min_y
    if width <= 0 or height <= 0:
        raise ValueError("타일 분할할 수 없는 경계입니다.")
    target_m2 = core_area_km2 * 1_000_000
    count = max(1, math.ceil(region.area / target_m2))
    columns = max(1, math.ceil(math.sqrt(count * width / height)))
    rows = max(1, math.ceil(count / columns))
    overlap_m = overlap_km * 1000

    while True:
        cell_w, cell_h = width / columns, height / rows
        planned = []
        too_large = False
        for row in range(rows):
            for column in range(columns):
                core = region.intersection(box(min_x + column * cell_w, min_y + row * cell_h,
                                                min_x + (column + 1) * cell_w, min_y + (row + 1) * cell_h))
                if core.is_empty or core.area < 1:
                    continue
                download = core.buffer(overlap_m)
                if download.area / 1_000_000 > MAX_AREA_KM2:
                    too_large = True
                    break
                core_wgs84 = gpd.GeoSeries([core], crs=metric.crs).to_crs("EPSG:4326").iloc[0]
                download_wgs84 = gpd.GeoSeries([download], crs=metric.crs).to_crs("EPSG:4326").iloc[0]
                planned.append({
                    "id": f"tile-r{row + 1:02d}-c{column + 1:02d}",
                    "row": row + 1, "column": column + 1,
                    "core_polygon": core_wgs84, "download_polygon": download_wgs84,
                    "core_area_km2": round(core.area / 1_000_000, 3),
                    "download_area_km2": round(download.area / 1_000_000, 3),
                    "core_bbox": [round(v, 7) for v in core_wgs84.bounds],
                })
            if too_large:
                break
        if not too_large:
            return planned
        # 길쭉한 행정구역도 버퍼 포함 100km² 미만이 되도록 긴 축을 우선 더 나눈다.
        if cell_w >= cell_h:
            columns += 1
        else:
            rows += 1


def _tile_manifest(job: dict, display_name: str, area_km2: float, tiles: list[dict], summaries: list[dict]) -> dict:
    return {
        "schema": "running-loop-tile-manifest-v1",
        "place": job["place"], "resolved_place": display_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "area_km2": round(area_km2, 3), "overlap_km": job["tile_overlap_km"],
        "max_segment_m": job["max_segment_m"],
        "tiles": [{
            "id": tile["id"], "file": summary["file"], "core_bbox": tile["core_bbox"],
            "core_area_km2": tile["core_area_km2"], "download_area_km2": tile["download_area_km2"],
            "nodes": summary["nodes"], "edges": summary["edges"], "bytes": summary["bytes"],
        } for tile, summary in zip(tiles, summaries)],
        "attribution": "© OpenStreetMap contributors (ODbL)",
    }


def verify_saved_graph(path: Path, expected_nodes: int, expected_edges: int, max_segment_m: float) -> dict:
    """디스크에 저장된 파일을 별도로 다시 읽어 완료 표시 전에 검증한다."""
    keys, nodes, edges, schema, max_length = {}, 0, 0, None, 0.0
    graph_el = None
    with path.open("rb") as stream:
        for event, el in ET.iterparse(stream, events=("start", "end")):
            tag = el.tag.rsplit("}", 1)[-1]
            if event == "start":
                if tag == "graph":
                    graph_el = el
                    if el.get("edgedefault") != "undirected":
                        raise ValueError("무방향 GraphML이 아닙니다.")
                continue
            if tag == "key":
                keys[el.attrib["id"]] = el.get("attr.name")
                el.clear()
            elif tag in {"node", "edge"}:
                data = {keys.get(c.get("key")): c.text for c in el}
                if tag == "node":
                    nodes += 1
                    lat, lng = float(data["y"]), float(data["x"])
                    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                        raise ValueError("잘못된 좌표입니다.")
                else:
                    edges += 1
                    length = float(data["length"])
                    if not 0 < length <= max_segment_m + 1e-5:
                        raise ValueError("분할 간격을 초과한 간선이 있습니다.")
                    coords = json.loads(data["coords"])
                    if len(coords) < 2 or any(not (-90 <= p[0] <= 90 and -180 <= p[1] <= 180) for p in coords):
                        raise ValueError("잘못된 도로 geometry입니다.")
                    max_length = max(max_length, length)
                graph_el.remove(el)
                el.clear()
            elif tag == "data" and keys.get(el.get("key")) == "schema_version":
                schema = el.text
    if schema != "running-loop-v1" or (nodes, edges) != (expected_nodes, expected_edges) or not edges:
        raise ValueError("저장된 GraphML의 스키마/노드/간선 수가 다릅니다.")
    return {"nodes": nodes, "edges": edges, "max_edge_m": max_length, "bytes": path.stat().st_size}


def cleanup_stage(job: dict) -> None:
    """이 작업 전용 임시 디렉터리만 지운다. 기존 GraphML이나 완료 폴더는 건드리지 않는다."""
    parent, stage = Path(job["parent"]).resolve(), Path(job["stage"]).resolve()
    if stage.parent != parent or not stage.name.startswith(".mapbuilder-"):
        raise ValueError("안전하지 않은 임시 디렉터리 경로입니다.")
    if stage.exists():
        shutil.rmtree(stage)


def run_tiled_build(job: dict, notify=lambda text: None) -> dict:
    """100km²를 넘는 행정구역을 overlap GraphML 타일과 manifest로 생성한다."""
    from map_processing import save_graph, segment_projected_graph
    stage, final = Path(job["stage"]), Path(job["final"])
    if final.exists():
        raise FileExistsError("결과 폴더가 이미 있습니다. 다시 시작해주세요.")
    stage.mkdir(exist_ok=False)
    try:
        notify("대형 지역 경계와 타일 계획을 준비 중…")
        ox, boundary, _polygon, area_km2, display_name = _resolve_boundary(job, notify)
        tiles = plan_large_area_tiles(boundary, core_area_km2=job["tile_core_area_km2"],
                                      overlap_km=job["tile_overlap_km"])
        notify(f"확인된 지역: {display_name} ({area_km2:.2f}km²), {len(tiles)}개 타일")
        summaries = []
        for index, tile in enumerate(tiles, 1):
            notify(f"[{index}/{len(tiles)}] {tile['id']} 다운로드·분할 중…")
            graph = _download_polygon(ox, tile["download_polygon"], notify)
            result = segment_projected_graph(graph, job["max_segment_m"])
            del graph
            result.graph.update(place=job["place"], resolved_place=display_name,
                                tile_id=tile["id"], tile_core_bbox=json.dumps(tile["core_bbox"]),
                                tile_overlap_km=job["tile_overlap_km"],
                                generated_at=datetime.now(timezone.utc).isoformat(),
                                attribution="© OpenStreetMap contributors (ODbL)")
            filename = f"{job['stem']}_{tile['id']}.graphml"
            file = stage / filename
            save_graph(result, file)
            summary = verify_saved_graph(file, len(result), result.number_of_edges(), job["max_segment_m"])
            summary["file"] = filename
            summaries.append(summary)
        manifest = _tile_manifest(job, display_name, area_km2, tiles, summaries)
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        cache = stage / ".osm-cache"
        if cache.is_dir():
            shutil.rmtree(cache)
        stage.rename(final)
        return {"folder": str(final), "manifest": str(final / "manifest.json"), "tiles": len(summaries),
                "place": display_name, "area_km2": round(area_km2, 3),
                "schema": "running-loop-tile-manifest-v1", "tile_summaries": summaries}
    except BaseException:
        cleanup_stage(job)
        raise


def run_build(job: dict, notify=lambda text: None, downloader=None) -> dict:
    """모든 결과를 임시 폴더에서 완성/검증한 뒤 새 결과 폴더로 원자적으로 이동한다."""
    if job.get("tile_large_area"):
        if downloader is not None:
            raise ValueError("대형 타일 모드는 실제 OSM 다운로드에서만 실행할 수 있습니다.")
        return run_tiled_build(job, notify)
    from map_processing import save_graph, segment_projected_graph
    stage, final = Path(job["stage"]), Path(job["final"])
    if final.exists():
        raise FileExistsError("결과 폴더가 이미 있습니다. 다시 시작해주세요.")
    stage.mkdir(exist_ok=False)
    try:
        graph, display_name = (downloader or download_projected)(job, notify)
        notify(f"도로를 최대 {job['max_segment_m']:g}m 간격으로 분할 중…")
        result = segment_projected_graph(graph, job["max_segment_m"])
        del graph
        result.graph.update(place=job["place"], resolved_place=display_name,
                            generated_at=datetime.now(timezone.utc).isoformat(),
                            attribution="© OpenStreetMap contributors (ODbL)")
        file = stage / job["filename"]
        notify("GraphML 저장 및 파일 재검증 중…")
        save_graph(result, file)
        summary = verify_saved_graph(file, len(result), result.number_of_edges(), job["max_segment_m"])
        # 이 한 번의 rename 이전에는 최종 폴더가 보이지 않는다. 취소/실패 시 반쪽 파일을 배포하지 않게 한다.
        cache = stage / ".osm-cache"
        if cache.is_dir():
            shutil.rmtree(cache)
        stage.rename(final)
        return {**summary, "folder": str(final), "file": str(final / job["filename"]),
                "place": display_name, "schema": "running-loop-v1"}
    except BaseException:
        cleanup_stage(job)
        raise


def worker_entry(job: dict, queue) -> None:
    """GUI가 멈추지 않도록 별도 프로세스에서 실행. Windows EXE에서도 spawn으로 동작."""
    try:
        result = run_build(job, lambda message: queue.put(("progress", message)))
        queue.put(("done", result))
    except Exception as exc:
        queue.put(("error", {"message": str(exc) or type(exc).__name__,
                             "detail": traceback.format_exc()[-12000:]}))
