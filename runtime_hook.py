"""Windows one-file EXE에 포함한 좌표계·GDAL 데이터 경로 지정.
사용자 PC에 별도로 설치된 Python/GDAL/PROJ에 의존하지 않는다.
"""
import os
from pathlib import Path
import sys

if getattr(sys,"frozen",False):
    base = Path(sys._MEIPASS)
    for path in [base / "pyproj/proj_dir/share/proj",base / "pyproj/share/proj"]:
        if (path / "proj.db").is_file():
            os.environ["PROJ_DATA"] = str(path)
            os.environ["PROJ_LIB"] = str(path)
            break
    for path in [base / "pyogrio/gdal_data",base / "osgeo/data/gdal"]:
        if path.is_dir():
            os.environ["GDAL_DATA"] = str(path)
            break
