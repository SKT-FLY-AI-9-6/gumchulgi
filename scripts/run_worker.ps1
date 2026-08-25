# GPU 노트북 네이티브 실행 — 필터 워커 (CUDA 감지 시 psegpu_full 사용)
# 사용: powershell -ExecutionPolicy Bypass -File scripts\run_worker.ps1
$root = Split-Path $PSScriptRoot -Parent
Set-Location "$root\server"
$env:PYTHONPATH = "$root\psepipe_v3_seam"
$env:PYTHONUTF8 = "1"
python -m worker.main
