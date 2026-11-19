# 一键启动：安装依赖（首次）→ 启动后端服务 → 打开浏览器
# 用法：在项目目录右键 PowerShell 运行，或执行  powershell -ExecutionPolicy Bypass -File .\start.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $ProjectRoot "backend"

# 优先使用本机 Python 3.11，其次 PATH 中的 python
$Python = "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

Write-Host "[1/3] 检查依赖..." -ForegroundColor Cyan
& $Python -m pip install -q -r (Join-Path $BackendDir "requirements.txt")

Write-Host "[2/3] 启动后端服务 (http://localhost:8080) ..." -ForegroundColor Cyan
Set-Location $BackendDir

# 等待服务就绪后自动打开浏览器
Start-Process powershell -ArgumentList "-Command", "Start-Sleep -Seconds 3; Start-Process 'http://localhost:8080'"

& $Python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
