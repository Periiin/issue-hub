# 停掉 issue-hub（按端口找进程，不用记 pid）
$Port = if ($env:ISSUEHUB_PORT) { $env:ISSUEHUB_PORT } else { '8090' }

$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $conns) {
    Write-Host "端口 $Port 上没有进程"
    exit 0
}

$pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
Write-Host "==> 停止 pid: $($pids -join ', ')"
foreach ($p in $pids) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host '还在占用，请手动检查'
} else {
    Write-Host '已停止'
}
