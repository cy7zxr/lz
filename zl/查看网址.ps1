# 读取晾知的公网分享网址
Write-Host '正在读取公网网址...' -ForegroundColor Cyan
Write-Host ''
try {
    $tunnels = Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 5
    $url = ($tunnels.tunnels | Where-Object { $_.public_url -like 'http*' } | Select-Object -First 1).public_url
    if ($url) {
        Write-Host '把这个网址发给朋友：' -ForegroundColor Green
        Write-Host ''
        Write-Host ("  " + $url + '/chat.html') -ForegroundColor Green
    } else { Write-Host '没有找到隧道，先双击 启动分享.ps1' -ForegroundColor Yellow }
} catch { Write-Host '读取失败，先双击 启动分享.ps1' -ForegroundColor Yellow }
Write-Host ''
Read-Host '按回车关闭'