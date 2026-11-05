$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 虚拟环境创建失败，请安装 Python 3.12 或更高版本。' }
}
$python = '.venv\Scripts\python.exe'
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python 依赖安装失败。' }
if ((-not (Test-Path 'node_modules\.ais-dependencies-installed')) -or ((Get-Item 'package-lock.json').LastWriteTime -gt (Get-Item 'node_modules\.ais-dependencies-installed' -ErrorAction SilentlyContinue).LastWriteTime)) {
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败。' }
    New-Item -ItemType File -Path 'node_modules\.ais-dependencies-installed' -Force | Out-Null
}
npm run build
if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
$port = if ($env:AIS_HTTP_PORT) { $env:AIS_HTTP_PORT } else { '8765' }
Write-Host "`nAIS Demo: http://127.0.0.1:$port`n按 Ctrl+C 结束。`n"
& $python -m uvicorn backend.app:app --host 127.0.0.1 --port $port
