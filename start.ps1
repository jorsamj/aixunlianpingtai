$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
python .\launcher.py
if ($LASTEXITCODE -ne 0) { Read-Host "启动失败，按回车关闭" }
