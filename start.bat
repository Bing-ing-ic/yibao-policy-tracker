@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
set PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe
if not exist "%PY%" set PY=python
echo [1/2] 安装依赖...
"%PY%" -m pip install -q -r requirements.txt
echo [2/2] 启动服务 http://localhost:8080
start "" cmd /c "ping 127.0.0.1 -n 4 >nul & start http://localhost:8080"
"%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port 8080
pause
