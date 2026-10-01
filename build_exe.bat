@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
echo Building the standalone Windows MapBuilder.exe...
echo Python 3.12 x64 is required on this BUILD PC only.
py -3.12 build_windows.py
if errorlevel 1 (
  echo.
  echo Build failed. Install Python 3.12 x64 with Tk support and the Python launcher.
  echo Read the error above. A failed build is NOT a usable EXE.
  pause
  exit /b 1
)
echo.
echo Build and offline smoke checks passed. Output: dist\MapBuilder.exe
pause
