# 로컬(Docker 없이) 서버 실행: API(8000) + worker
$root = $PSScriptRoot
Set-Location "$root\server"
Get-Content .env | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
  $k,$v = $_ -split '=',2; [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim())
}
$env:DATA_DIR = "$root\data"
$env:PYTHONPATH = "$root\server;$root\psepipe_v3_seam"
New-Item -ItemType Directory -Force $env:DATA_DIR | Out-Null
Start-Process python -ArgumentList "-m worker.main" -NoNewWindow
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
