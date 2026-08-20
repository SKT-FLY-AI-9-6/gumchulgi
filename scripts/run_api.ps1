# GPU 노트북 네이티브 실행 — API 서버 (스펙 2026-08-20 개정 4항)
# 사용: powershell -ExecutionPolicy Bypass -File scripts\run_api.ps1
$root = Split-Path $PSScriptRoot -Parent
Set-Location "$root\server"
$env:PYTHONPATH = "$root\psepipe_v3_seam"
$env:PYTHONUTF8 = "1"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
