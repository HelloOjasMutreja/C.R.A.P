@echo off
rem Double-click to start the live phone demo. Keep this window open while demoing.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
    echo Setting up Python packages. This is a large download, run once only...
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)

.venv\Scripts\python.exe -m live %*
pause
