"""MapBuilder의 미터 단위 간선 분할 및 GraphML 저장 모듈.

GUI 및 서버와 독립적인 순수 지도 처리 함수들이다.
출력은 기존에 만든 용봉동 지도와 같은 running-loop-v1 스키마다.
곡선을 유지하고 reciprocal edge는 호출자가 먼저 무방향으로 통합해야 한다.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import networkx as nx
from pyproj import CRS, Transformer
from shapely.geometry import LineString
from shapely.ops import substring

SCHEMA = "running-loop-v1"


def _is_crossing(data: dict) -> bool:
    """기존 OSM 노드에 실제 태그가 있는 경우만 횡단 지점으로 표시한다."""
    return data.get("highway") == "crossing" or data.get("crossing") not in (
        None, "no", "none", "",
    )


def _oriented_geometry(graph: nx.MultiGraph, u: int, v: int, data: dict) -> LineString:
    """간선 geometry 순서를 u→v로 맞추고 끝점을 실제 노드 좌표와 일치시킨다.

    양방향 간선을 무방향으로 바꾸면 geometry가 v→u 순서인 경우도 있다.
    이를 무시하면 역방향으로 이어지거나 순간이동하는 경로가 만들어진다.
    """
    a = (float(graph.nodes[u]["x"]), float(graph.nodes[u]["y"]))
    b = (float(graph.nodes[v]["x"]), float(graph.nodes[v]["y"]))
    line = data.get("geometry")
    if line is None:
        if u == v:
            raise ValueError(f"자기 루프 {u}에 geometry가 없습니다.")
        line = LineString([a, b])
    if not isinstance(line, LineString):
        raise ValueError(f"{u}-{v}: LineString이 아닌 geometry입니다.")
    coords = [(float(p[0]), float(p[1])) for p in line.coords]
    if len(coords) < 2:
        raise ValueError(f"{u}-{v}: geometry가 너무 짧습니다.")
    forward = math.dist(a, coords[0]) + math.dist(b, coords[-1])
    backward = math.dist(a, coords[-1]) + math.dist(b, coords[0])
    if backward < forward:
        coords.reverse()
    if max(math.dist(a, coords[0]), math.dist(b, coords[-1])) > 2.0:
        raise ValueError(f"{u}-{v}: geometry 끝점이 노드에서 2m 이상 벗어났습니다.")
    coords[0], coords[-1] = a, b
    return LineString(coords)


def segment_projected_graph(
    graph: nx.MultiGraph, max_segment_m: float = 50.0
) -> nx.MultiGraph:
    """미터 단위로 투영된 무방향 MultiGraph를 잘게 나눈다.

    중요:
    * 위경도(도 단위)에서 Shapely.length를 사용하면 50m가 아니라 50도가 된다.
    * 직선 보간만 하지 않고 원래 곡선을 substring으로 잘라 곡선 형태를 보존한다.
    * reciprocal edge를 먼저 합친 뒤 한 번만 분할해야 양방향에 같은 가상 노드가
      쓰인다. 같은 좌표라는 이유로 서로 다른 도로/고가도로 노드를 합치지는 않는다.
    * 원래 양끝 노드 ID는 유지하고 가상 노드만 충돌하지 않는 음수 ID를 사용한다.
    """
    if graph.is_directed() or not graph.is_multigraph():
        raise ValueError("투영된 무방향 nx.MultiGraph를 넘겨주세요.")
    if not math.isfinite(max_segment_m) or max_segment_m <= 0:
        raise ValueError("max_segment_m은 양수여야 합니다.")
    crs = CRS.from_user_input(graph.graph.get("crs"))
    if not crs.is_projected or any(
        abs(axis.unit_conversion_factor - 1.0) > 1e-9 for axis in crs.axis_info[:2]
    ):
        raise ValueError("좌표계가 미터 단위 투영 좌표계여야 합니다(예: EPSG:32652).")
    to_wgs84 = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    result = nx.MultiGraph()
    result.graph.update(
        schema_version=SCHEMA,
        crs="EPSG:4326",
        metric_crs=crs.to_string(),
        max_segment_m=float(max_segment_m),
    )
    # router는 x/y를 위경도, mx/my를 지역의 미터 좌표로 해석한다.
    for node, data in graph.nodes(data=True):
        mx, my = float(data["x"]), float(data["y"])
        lng, lat = to_wgs84.transform(mx, my)
        result.add_node(int(node), x=lng, y=lat, mx=mx, my=my,
                        virtual=False, crossing=_is_crossing(data))
    virtual_id = min(-1, min(result.nodes, default=0) - 1)
    edge_id = 0
    for parent_id, (u, v, key, data) in enumerate(graph.edges(keys=True, data=True)):
        line = _oriented_geometry(graph, u, v, data)
        length = line.length  # 원본 OSM length가 아니라 투영된 곡선의 실제 길이
        if not math.isfinite(length) or length <= 1e-6:
            raise ValueError(f"{u}-{v}/{key}: 길이가 0이거나 잘못된 간선입니다.")
        count = max(1, math.ceil(length / max_segment_m))
        # 원형 도로(self-loop)도 정상적인 노드 순환으로 바꾼다.
        if u == v:
            count = max(3, count)
        nodes = [int(u)]
        for i in range(1, count):
            point = line.interpolate(length * i / count)
            lng, lat = to_wgs84.transform(point.x, point.y)
            result.add_node(virtual_id, x=lng, y=lat, mx=point.x, my=point.y,
                            virtual=True, crossing=False)
            nodes.append(virtual_id)
            virtual_id -= 1
        nodes.append(int(v))
        for i, (a, b) in enumerate(zip(nodes, nodes[1:])):
            part = substring(line, length * i / count, length * (i + 1) / count)
            lngs, lats = to_wgs84.transform(
                [p[0] for p in part.coords], [p[1] for p in part.coords]
            )
            # JSON 순서는 프런트가 쓰는 [lat, lng]. 반대 방향 탐색 때는 router가 뒤집는다.
            coords = [[lat, lng] for lng, lat in zip(lngs, lats)]
            coords[0] = [result.nodes[a]["y"], result.nodes[a]["x"]]
            coords[-1] = [result.nodes[b]["y"], result.nodes[b]["x"]]
            result.add_edge(
                a, b, key=edge_id, length=float(part.length),
                geom_from=a, geom_to=b, parent_id=parent_id,
                coords=json.dumps(coords, separators=(",", ":")),
            )
            edge_id += 1
    # 필요한 지표만 남긴다. 원래 OSM의 name/osmid 목록 등 거대한 부가 속성은 저장하지 않는다.
    validate_segmented_graph(result, max_segment_m)
    return result


def validate_segmented_graph(graph: nx.MultiGraph, max_segment_m: float) -> None:
    """저장 전 최대 길이, 경로 끝점, 분할 결과를 실제로 검증한다."""
    if not graph.number_of_edges():
        raise ValueError("간선이 없는 지도입니다.")
    for u, v, data in graph.edges(data=True):
        if not 0 < data["length"] <= max_segment_m + 1e-6:
            raise ValueError(f"간선 {u}-{v}의 길이 {data['length']}가 잘못됐습니다.")
        coords = json.loads(data["coords"])
        a, b = data["geom_from"], data["geom_to"]
        if {a, b} != {u, v} or coords[0] != [graph.nodes[a]["y"], graph.nodes[a]["x"]]:
            raise ValueError("간선 geometry 시작점이 잘못됐습니다.")
        if coords[-1] != [graph.nodes[b]["y"], graph.nodes[b]["x"]]:
            raise ValueError("간선 geometry 끝점이 잘못됐습니다.")


def save_graph(graph: nx.MultiGraph, path: Path) -> None:
    """부분 저장된 파일이 배포되지 않도록 임시 파일을 쓴 뒤 교체한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    nx.write_graphml(graph, temp, encoding="utf-8")
    temp.replace(path)


