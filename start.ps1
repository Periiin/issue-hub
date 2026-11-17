# issue-hub 一键启动（Windows / PowerShell）
#   .\start.ps1            仅启动（首次会自动装后端依赖、构建前端）
#   .\start.ps1 -Build     强制重新构建前端
#   $env:ISSUEHUB_PORT=8091; .\start.ps1   换端口
param([switch]$Build)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$Port = if ($env:ISSUEHUB_PORT) { $env:ISSUEHUB_PORT } else { '8090' }
$VenvPython = Join-Path $PSScriptRoot 'backend\.venv\Scripts\python.exe'

if (-not (Test-Path $VenvPython)) {
    Write-Host '==> 创建 Python 虚拟环境'
    py -m venv backend\.venv
}

Write-Host '==> 安装后端依赖'
& $VenvPython -m pip -q install -r backend\requirements.txt

if ($Build -or -not (Test-Path 'frontend\dist')) {
    Write-Host '==> 构建前端'
    Push-Location frontend
    try {
        npm install --no-fund --no-audit
        npm run build
    } finally {
        Pop-Location
    }
}

$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Error "端口 $Port 已被占用，先执行 .\stop.ps1 或换 ISSUEHUB_PORT"
    exit 1
}

Write-Host "==> 启动 http://127.0.0.1:$Port"
& $VenvPython -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $Port
