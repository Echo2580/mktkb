@echo off
title MKTKB Local Launcher
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing project Python: .venv\Scripts\python.exe
  pause
  exit /b 1
)
set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1
set OPENBLAS_NUM_THREADS=1
".venv\Scripts\python.exe" -B "tools\start_local.py" --offline
if errorlevel 1 pause
