"""Windows 빌드 PC/CI 전용. 성공한 EXE만 배포 대상으로 남긴다."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def command(args, timeout=1800, **kwargs):
    print("+", " ".join(map(str,args)),flush=True)
    return subprocess.run(list(map(str,args)),cwd=ROOT,check=True,timeout=timeout,**kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ci",action="store_true")
    parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("실제 Windows EXE 빌드는 Windows x64에서만 가능합니다. README의 GitHub Actions 방법도 사용할 수 있습니다.")
    if sys.version_info[:2] != (3,12) or struct.calcsize("P") != 8:
        raise SystemExit("빌드 PC에는 Python 3.12 x64를 사용해주세요.")
    python = ROOT / ".build-venv/Scripts/python.exe"
    if not python.is_file():
        command([sys.executable,"-m","venv",ROOT / ".build-venv"])
    command([python,"-m","pip","install","--upgrade","pip"])
    command([python,"-m","pip","install","-r",ROOT / "requirements-build.txt"])
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    executable = dist / "MapBuilder.exe"
    reports = [dist / "self-test-result.json",dist / "gui-smoke-result.json"]
    for path in [executable,*reports,dist / "build-info.json"]:
        path.unlink(missing_ok=True)
    command([python,"-m","PyInstaller","--noconfirm","--clean",ROOT / "MapBuilder.spec"])
    try:
        # 이름만 .exe인 파일이 아니라 x64 Windows PE인지도 확인한다.
        with executable.open("rb") as handle:
            if handle.read(2) != b"MZ":
                raise RuntimeError("Windows 실행 파일이 아닙니다.")
            handle.seek(0x3C)
            offset = struct.unpack("<I",handle.read(4))[0]
            handle.seek(offset)
            if handle.read(4) != b"PE\x00\x00" or struct.unpack("<H",handle.read(2))[0] != 0x8664:
                raise RuntimeError("Windows x64 실행 파일이 아닙니다.")
        # Python 소스가 아닌, 만들어진 EXE 자체를 실행하여 DLL/PROJ/Tk/spawn까지 확인.
        # GIS import가 많은 one-file EXE라 최초 압축 해제 시간을 충분히 준다.
        env = dict(os.environ,MAPBUILDER_CACHE_DIR=str(dist / "self-test-cache"))
        command([executable,"--self-test",reports[0]],timeout=300,env=env)
        command([executable,"--gui-smoke",reports[1]],timeout=120,env=env)
        for report in reports:
            if not json.loads(report.read_text(encoding="utf-8")).get("ok"):
                raise RuntimeError(f"EXE 검사 실패: {report}")
        requirements = command([python,"-m","pip","freeze"],capture_output=True,text=True)
        (dist / "build-requirements.txt").write_text(requirements.stdout,encoding="utf-8")
        digest = hashlib.sha256()
        with executable.open("rb") as handle:
            for chunk in iter(lambda:handle.read(1024*1024),b""):
                digest.update(chunk)
        info = {"file":"MapBuilder.exe","sha256":digest.hexdigest(),"bytes":executable.stat().st_size,
                "builder_python":sys.version,"platform":platform.platform(),"offline_exe_tests_passed":True,
                "live_osm_download_tested":False,"code_signed":False}
        (dist / "build-info.json").write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding="utf-8")
        print(f"완료: {executable}\n실행 PC에는 Python이 필요하지 않습니다.")
    except BaseException:
        # 빌드 파일이 생겼더라도 테스트 실패 시 배포본으로 오인하지 않게 다른 이름으로 보관한다.
        if executable.exists():
            failed = executable.with_suffix(".failed-build")
            failed.unlink(missing_ok=True)
            executable.replace(failed)
        raise


if __name__ == "__main__":
    main()
