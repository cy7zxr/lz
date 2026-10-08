# 晾知 - 一键分享启动器
$Host.UI.RawUI.WindowTitle = '晾知 - 一键分享启动器'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$cpolarExe = Join-Path $root 'tunnel\extracted\cpolar\cpolar.exe'
$pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonExe) { $pythonExe = 'D:\python\python.exe' }

Write-Host '============================================' -ForegroundColor Cyan
Write-Host '  正在启动晾知智能体分享服务...' -ForegroundColor Cyan
Write-Host '============================================' -ForegroundColor Cyan
Write-Host ''

# 启动本地服务器（新窗口，日志写到 server.log）
Start-Process -FilePath $pythonExe -ArgumentList 'server.py' -WorkingDirectory $root -WindowStyle Normal -RedirectStandardOutput (Join-Path $root 'server.out.log') -RedirectStandardError (Join-Path $root 'server.err.log')
Start-Sleep -Seconds 3

# 启动 cpolar 隧道（新窗口，日志写到 cpolar.log）
Start-Process -FilePath $cpolarExe -ArgumentList 'http','8000' -WorkingDirectory (Split-Path $cpolarExe) -WindowStyle Normal -RedirectStandardOutput (Join-Path $root 'cpolar.out.log') -RedirectStandardError (Join-Path $root 'cpolar.err.log')

Write-Host '两个服务已在新窗口启动'
Write-Host '等待隧道建立...' -ForegroundColor Yellow
Start-Sleep -Seconds 8

Write-Host ''
Write-Host '============ 把这个网址发给朋友 ============' -ForegroundColor Green
$url = $null
try {
    $tunnels = Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 5
    $url = ($tunnels.tunnels | Where-Object { $_.public_url -like 'http*' } | Select-Object -First 1).public_url
} catch {}
if ($url) { Write-Host ("  " + $url + '/chat.html') -ForegroundColor Green }
else { Write-Host '  还没读到网址，等几秒后双击 查看网址.ps1' -ForegroundColor Yellow }
Write-Host '============================================' -ForegroundColor Green
Write-Host ''
Write-Host '停止分享：关闭那两个黑色窗口。' -ForegroundColor Gray
Write-Host ''
Read-Host '按回车关闭本窗口'