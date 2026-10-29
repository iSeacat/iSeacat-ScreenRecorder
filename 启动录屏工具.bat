@echo off
cd /d "%~dp0"
if exist "%~dp0runtime\python\pythonw.exe" (
  start "" "%~dp0runtime\python\pythonw.exe" "%~dp0grace_recorder_gui.py"
  exit /b
)
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0grace_recorder_gui.py"
  exit /b
)
echo Python runtime not found. Run first:  python make_portable.py
pause
