# -*- mode: python ; coding: utf-8 -*-
# Windows에서만 빌드한다. PyInstaller는 Linux→Windows 크로스 빌드를 지원하지 않는다.
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

if sys.platform != "win32":
    raise SystemExit("Windows x64 + Python 3.12 환경에서 빌드해주세요.")
root = Path(SPECPATH)
datas, binaries, hiddenimports = [], [], []
# GIS 패키지는 DLL 및 proj.db/GDAL 데이터가 있어야 작동한다.
# 기본 PyInstaller hook과 함께 부가 파일/동적 import를 명시적으로 수집한다.
for package in ("osmnx","geopandas","pyogrio","pyproj","shapely"):
    data, binary, imports = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += imports
for package in ("osmnx","networkx","geopandas","pyogrio","pyproj","shapely","pandas","numpy"):
    datas += copy_metadata(package)
hiddenimports += ["tkinter","tkinter.ttk","tkinter.filedialog","tkinter.messagebox",
                  "numpy","pandas","networkx.readwrite.graphml","certifi","self_test"]
a = Analysis(
    [str(root / "map_builder.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(root / "runtime_hook.py")],
    # 이 생성기는 지도 플로팅/최근접 노드 검색/ML/웹 서버를 사용하지 않는다.
    excludes=["matplotlib","scipy","sklearn","IPython","pytest","fastapi","uvicorn"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,a.scripts,a.binaries,a.datas,[],
    name="MapBuilder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
