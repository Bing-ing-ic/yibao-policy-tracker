# 本地启动器（推荐：直接双击 start.bat 或桌面快捷方式）。
# 本脚本仅作为 PowerShell 入口，实际逻辑统一由 start.bat 承载。
Start-Process -FilePath (Join-Path $PSScriptRoot "start.bat") -WorkingDirectory $PSScriptRoot
