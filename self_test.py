"""EXE가 의존 DLL/좌표계 데이터를 실제로 포함했는지 검사하는 오프라인 자체 검사.

사용자가 평소 실행할 때는 호출하지 않는다. Windows 빌드 완료 후 자동 실행한다.
생성하는 지도는 가상 사각형이며 실제 도로 데이터가 아니다.
"""
import json
import multiprocessing as mp
from pathlib import Path
import tempfile
import traceback


def synthetic_download(job, notify):
    import networkx as nx
    from pyproj import Transformer
    from shapely.geometry import LineString
    x,y = Transformer.from_crs("EPSG:4326","EPSG:32652",always_xy=True).transform(126.90,35.18)
    graph = nx.MultiGraph(crs="EPSG:32652")
    for n,(dx,dy) in enumerate([(0,0),(120,0),(120,120),(0,120)]):
        graph.add_node(n,x=x+dx,y=y+dy,highway="crossing" if n == 0 else "junction")
    for u,v in [(0,1),(1,2),(2,3),(3,0)]:
        a,b = graph.nodes[u],graph.nodes[v]
        graph.add_edge(u,v,geometry=LineString([(a["x"],a["y"]),(b["x"],b["y"])]))
    notify("자체 검사: 합성 도로 처리")
    return graph,"SYNTHETIC SELF TEST - NOT REAL OSM DATA"


def synthetic_worker(job, queue):
    from builder_core import run_build
    try:
        result = run_build(job,lambda text:queue.put(("progress",text)),downloader=synthetic_download)
        queue.put(("done",result))
    except Exception as exc:
        queue.put(("error",{"message":str(exc),"detail":traceback.format_exc()}))


def run_self_test(report_path: Path) -> int:
    report_path = report_path.resolve()
    report_path.parent.mkdir(parents=True,exist_ok=True)
    try:
        import osmnx as ox
        import geopandas as gpd
        import pandas as pd
        import numpy as np
        import pyproj
        import shapely
        import networkx as nx
        # Windows 배포에서는 실제 GDAL DLL import도 확인한다.
        import pyogrio
        import tkinter as tk
        from builder_core import new_job,run_build
        # 한글/공백 경로 저장과 좌표계 데이터(PROJ)를 포함한 전체 저장 파이프라인.
        with tempfile.TemporaryDirectory(prefix="MapBuilder_검증_",dir=report_path.parent) as folder:
            job = new_job("합성 검사 지역",folder,"한글 지도",50)
            result = run_build(job,downloader=synthetic_download)
            saved = nx.read_graphml(result["file"])
            assert saved.graph["schema_version"] == "running-loop-v1"
            assert result["max_edge_m"] <= 50.00001 and result["edges"] == 12
            # frozen EXE의 multiprocessing 재귀 실행/누락 모듈도 실제로 검사한다.
            context = mp.get_context("spawn")
            events = context.Queue()
            child_job = new_job("자식 프로세스 검사",folder,"spawn_test",30)
            process = context.Process(target=synthetic_worker,args=(child_job,events))
            process.start()
            try:
                while True:
                    kind,data = events.get(timeout=120)
                    if kind == "error":
                        raise RuntimeError(data["detail"])
                    if kind == "done":
                        assert data["max_edge_m"] <= 30.00001
                        break
                process.join(timeout=30)
                assert process.exitcode == 0
            finally:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=10)
                events.close()
        root = tk.Tk()
        root.withdraw()
        root.update()
        root.destroy()
        versions = {"osmnx":ox.__version__,"geopandas":gpd.__version__,"pandas":pd.__version__,
                    "numpy":np.__version__,"pyproj":pyproj.__version__,"shapely":shapely.__version__,
                    "networkx":nx.__version__,"pyogrio":pyogrio.__version__}
        report = {"ok":True,"versions":versions,"nodes":result["nodes"],"edges":result["edges"],
                  "max_edge_m":result["max_edge_m"],"tk_test":True,"spawn_test":True,"live_osm_download_tested":False}
        code = 0
    except Exception:
        report = {"ok":False,"error":traceback.format_exc()}
        code = 1
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return code
