@echo off
setlocal EnableDelayedExpansion
title Yibao Policy Tracker - Local Launcher
cd /d "%~dp0backend"

set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PY%" set "PY=python"

rem 1. Port already listening: open browser only
netstat -ano | findstr /C:":8080 " | findstr /C:"LISTENING" >nul
if !errorlevel!==0 (
  echo.
  echo [INFO] Service already running at http://localhost:8080, opening browser...
  start "" http://localhost:8080
  timeout /t 2 >nul
  exit /b 0
)

rem 2. Check Python
"%PY%" --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python 3.11 not found. Install Python and add it to PATH.
  pause
  exit /b 1
)

rem 3. Install deps on first run only (delete .deps-installed after requirements change)
if not exist ".deps-installed" (
  echo [1/3] First run: installing dependencies...
  "%PY%" -m pip install -q -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] Dependency install failed. Check network and retry.
    pause
    exit /b 1
  )
  echo done> ".deps-installed"
) else (
  echo [1/3] Dependencies ready.
)

echo [2/3] Starting backend http://localhost:8080 ...
echo [3/3] Browser opens automatically. Close this window to stop the service.
start "" cmd /c "ping 127.0.0.1 -n 5 >nul & start http://localhost:8080"

"%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port 8080

echo.
echo Service stopped.
pause