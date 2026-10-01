"""다운로드는 합성 입력으로 바꾸되 파일 생성·실제 OSMnx 변환·GUI는 직접 실행한다."""
import json
import os
from pathlib import Path
import time

import networkx as nx
import pytest

from builder_core import cleanup_stage, new_job, run_build, safe_stem, verify_saved_graph
from map_processing import segment_projected_graph
from self_test import synthetic_download, synthetic_worker


@pytest.mark.parametrize("name,expected",[("광주 북구 용봉동","광주_북구_용봉동"),("a/b\\c:d","a_b_c_d"),("CON","map_CON"),("NUL.txt","map_NUL.txt"),("..","map"),("  ","map"),("../a","a"),("ok..  ","ok"),("ＣＯＮ","map_CON")])
def test_windows_names(name,expected):
    assert safe_stem(name) == expected


@pytest.mark.parametrize("value",[0,-1,9.9,51,float("nan"),float("inf"),"abc"])
def test_bad_segment(tmp_path,value):
    with pytest.raises(ValueError):
        new_job("용봉동",tmp_path,max_segment_m=value)


def test_bad_place_or_directory(tmp_path):
    with pytest.raises(ValueError):
        new_job("",tmp_path)
    with pytest.raises(ValueError):
        new_job("용봉동",tmp_path / "does-not-exist")
    with pytest.raises(ValueError):
        new_job("용봉동","")


def test_extension_not_duplicated(tmp_path):
    assert new_job("용봉동",tmp_path,"yongbong_map.graphml")["filename"] == "yongbong_map.graphml"


def test_work_cache_not_published(tmp_path):
    def downloader(job,notify):
        cache=Path(job["stage"]) / ".osm-cache"
        cache.mkdir()
        (cache / "response.json").write_text("{}")
        return synthetic_download(job,notify)
    result=run_build(new_job("용봉동",tmp_path),downloader=downloader)
    assert len(list(Path(result["folder"]).iterdir())) == 1


def test_unique_output_and_no_overwrite(tmp_path):
    first = new_job("용봉동",tmp_path)
    second = new_job("용봉동",tmp_path)
    assert first["final"] != second["final"] and first["stage"] != second["stage"]
    assert not Path(first["final"]).exists()
    existing = tmp_path / "existing.graphml"
    existing.write_text("KEEP",encoding="utf-8")
    result = run_build(first,downloader=synthetic_download)
    assert existing.read_text() == "KEEP"
    assert len(list(Path(result["folder"]).iterdir())) == 1
    assert Path(result["file"]).suffix == ".graphml"
    assert not Path(first["stage"]).exists()
    with pytest.raises(FileExistsError):
        run_build(first,downloader=synthetic_download)


@pytest.mark.parametrize("spacing",[10,30,50])
def test_saved_graph_and_micro_segments(tmp_path,spacing):
    job = new_job("광주광역시 북구 용봉동",tmp_path,"한글 지도",spacing)
    progress = []
    result = run_build(job,progress.append,synthetic_download)
    graph = nx.read_graphml(result["file"],node_type=int,force_multigraph=True)
    assert result["max_edge_m"] <= spacing + 1e-5
    assert graph.graph["schema_version"] == "running-loop-v1"
    assert graph.graph["place"] == job["place"]
    assert not graph.is_directed() and nx.is_connected(graph)
    assert sum(d["length"] for *_,d in graph.edges(data=True)) == pytest.approx(480)
    assert any(d["crossing"] for _,d in graph.nodes(data=True))
    assert any(d["virtual"] for _,d in graph.nodes(data=True))
    for u,v,d in graph.edges(data=True):
        coords = json.loads(d["coords"])
        a,b = d["geom_from"],d["geom_to"]
        assert {a,b} == {u,v}
        assert coords[0] == [graph.nodes[a]["y"],graph.nodes[a]["x"]]
        assert coords[-1] == [graph.nodes[b]["y"],graph.nodes[b]["x"]]
    assert progress


def broken_download(job,notify):
    raise ConnectionError("TEST network failure")


def test_failure_removes_partial_output(tmp_path):
    job = new_job("용봉동",tmp_path)
    with pytest.raises(ConnectionError):
        run_build(job,downloader=broken_download)
    assert not Path(job["stage"]).exists() and not Path(job["final"]).exists()


def test_cleanup_cannot_remove_other_folder(tmp_path):
    keep = tmp_path / "keep"
    keep.mkdir()
    job = new_job("용봉동",tmp_path)
    job["stage"] = str(keep)
    with pytest.raises(ValueError):
        cleanup_stage(job)
    assert keep.is_dir()


def test_bad_saved_file_rejected(tmp_path):
    job = new_job("용봉동",tmp_path)
    result = run_build(job,downloader=synthetic_download)
    with pytest.raises(ValueError):
        verify_saved_graph(Path(result["file"]),999,999,50)
    with pytest.raises(ValueError):
        verify_saved_graph(Path(result["file"]),result["nodes"],result["edges"],1)


def test_empty_map_never_published(tmp_path):
    job = new_job("용봉동",tmp_path)
    with pytest.raises(ValueError):
        run_build(job,downloader=lambda j,n:(nx.MultiGraph(crs="EPSG:32652"),"empty"))
    assert not Path(job["final"]).exists()


def test_curved_and_reversed_geometry():
    from shapely.geometry import LineString
    graph,_ = synthetic_download({},lambda m:None)
    graph.remove_edges_from(list(graph.edges(keys=True)))
    a,b = graph.nodes[0],graph.nodes[1]
    curve = LineString([(b["x"],b["y"]),(a["x"]+60,a["y"]+60),(a["x"],a["y"])])
    graph.add_edge(0,1,geometry=curve)
    result = segment_projected_graph(graph,50)
    assert sum(d["length"] for *_,d in result.edges(data=True)) == pytest.approx(curve.length)
    assert result.number_of_edges() == 4


def test_real_osmnx_transforms_with_fake_download(tmp_path,monkeypatch):
    import osmnx as ox
    import geopandas as gpd
    from pyproj import Transformer
    from shapely.geometry import box
    metric,_ = synthetic_download({},lambda m:None)
    raw = nx.MultiDiGraph(crs="EPSG:4326")
    inverse = Transformer.from_crs("EPSG:32652","EPSG:4326",always_xy=True)
    for node,d in metric.nodes(data=True):
        lng,lat = inverse.transform(d["x"],d["y"])
        raw.add_node(node,x=lng,y=lat,highway=d["highway"])
    for i,(u,v) in enumerate(metric.edges()):
        for a,b in [(u,v),(v,u)]:
            raw.add_edge(a,b,osmid=i,length=120,highway="footway")
    boundary = gpd.GeoDataFrame({"display_name":["합성 테스트 경계"]},geometry=[box(126.898,35.178,126.905,35.185)],crs="EPSG:4326")
    monkeypatch.setattr(ox,"geocode_to_gdf",lambda p:boundary)
    calls=[]
    monkeypatch.setattr(ox,"graph_from_polygon",lambda p,**kwargs:calls.append(kwargs) or raw)
    monkeypatch.setenv("MAPBUILDER_CACHE_DIR",str(tmp_path / "cache"))
    result = run_build(new_job("용봉동",tmp_path))
    assert result["max_edge_m"] <= 50.00001
    assert result["edges"] == 12
    assert result["place"] == "합성 테스트 경계"
    assert calls == [{"network_type":"walk","simplify":False,"retain_all":False}]


def test_large_area_is_rejected_before_download(tmp_path,monkeypatch):
    import osmnx as ox
    import geopandas as gpd
    from shapely.geometry import box
    boundary = gpd.GeoDataFrame({"display_name":["too large"]},geometry=[box(126,35,127,36)],crs="EPSG:4326")
    monkeypatch.setattr(ox,"geocode_to_gdf",lambda p:boundary)
    monkeypatch.setattr(ox,"graph_from_polygon",lambda *a,**kw:pytest.fail("too large area was downloaded"))
    with pytest.raises(ValueError,match="km²"):
        run_build(new_job("광주광역시",tmp_path))


def slow_worker(job,events):
    Path(job["stage"]).mkdir()
    (Path(job["stage"])/"partial.tmp").write_text("partial")
    time.sleep(60)


def failed_worker(job,events):
    events.put(("error",{"message":"네트워크 오류 테스트","detail":"synthetic"}))


def pump(root,condition,timeout=30):
    end=time.monotonic()+timeout
    while not condition() and time.monotonic()<end:
        root.update()
        time.sleep(.025)
    assert condition(),"GUI wait timed out"


@pytest.fixture
def gui(tmp_path):
    if os.name != "nt" and not os.getenv("DISPLAY"):
        pytest.skip("Tk 테스트는 Xvfb 또는 실제 화면이 필요합니다.")
    import tkinter as tk
    from map_builder import MapBuilderApp
    root=tk.Tk()
    root.withdraw()
    app=MapBuilderApp(root,worker_target=synthetic_worker)
    app.destination.set(str(tmp_path))
    yield root,app
    if app.process is not None:
        app.cancel()
        pump(root,lambda:app.process is None)
    root.destroy()


def test_gui_success_and_spawn(gui):
    root,app=gui
    app.start()
    assert str(app.start_button["state"]) == "disabled"
    pump(root,lambda:app.process is None)
    assert app.status.get().startswith("완료")
    assert Path(app.last_folder).is_dir()
    assert str(app.start_button["state"]) == "normal"
    assert str(app.open_button["state"]) == "normal"


def test_gui_cancellation_removes_partial(gui):
    root,app=gui
    app.worker_target=slow_worker
    app.start()
    pump(root,lambda:Path(app.job["stage"]).exists())
    app.cancel()
    pump(root,lambda:app.process is None)
    assert not Path(app.job["stage"]).exists()
    assert not Path(app.job["final"]).exists()
    assert "취소" in app.status.get()
    assert str(app.start_button["state"]) == "normal"


def test_gui_error_and_retry(gui):
    root,app=gui
    app.worker_target=failed_worker
    app.start()
    pump(root,lambda:app.process is None)
    assert "실패" in app.status.get()
    app.worker_target=synthetic_worker
    app.start()
    pump(root,lambda:app.process is None)
    assert "완료" in app.status.get()


def test_gui_invalid_input_does_not_spawn(gui,monkeypatch):
    root,app=gui
    errors=[]
    monkeypatch.setattr(app.messagebox,"showerror",lambda *a,**kw:errors.append(a))
    app.place.set("")
    app.start()
    assert app.process is None and errors
