# ============================================================
# BiliMind - 注册 Windows 服务脚本
# ============================================================
#
# 用途：使用 NSSM 将后端、前端注册为 Windows 服务，开机自启
# 前置条件：
#   - NSSM 已下载到 C:\Tools\nssm\nssm.exe
#   - Caddy 已下载到 C:\Tools\Caddy\caddy.exe
#   - deploy.ps1 已执行成功
#   - 手动测试 backend / frontend / caddy 均正常
#
# 执行方式：以管理员身份运行 PowerShell：
#   powershell -ExecutionPolicy Bypass -File C:\BiliMind\scripts\install-services.ps1
#
# ============================================================

#Requires -RunAsAdministrator

$ErrorActionPreference = "Continue"

$PROJECT_ROOT = "C:\BiliMind"
$NSSM         = "C:\Tools\nssm\nssm.exe"
$CADDY        = "C:\Tools\Caddy\caddy.exe"
$LOG_DIR      = "$PROJECT_ROOT\logs"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  BiliMind - Register Windows Services"
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# --- 检查 NSSM ---
if (-not (Test-Path $NSSM)) {
    Write-Host "[ERROR] NSSM not found at $NSSM" -ForegroundColor Red
    Write-Host "Download from: https://nssm.cc/download" -ForegroundColor Yellow
    Write-Host "Extract nssm.exe (64-bit) to C:\Tools\nssm\nssm.exe" -ForegroundColor Yellow
    exit 1
}

# --- 检查 Caddy ---
if (-not (Test-Path $CADDY)) {
    Write-Host "[ERROR] Caddy not found at $CADDY" -ForegroundColor Red
    Write-Host "Download from: https://caddyserver.com/download" -ForegroundColor Yellow
    Write-Host "Save caddy.exe to C:\Tools\Caddy\caddy.exe" -ForegroundColor Yellow
    exit 1
}

# ============================================================
# 服务 1：BiliMind-Backend (FastAPI)
# ============================================================
Write-Host "[1/3] Installing BiliMind-Backend service ..." -ForegroundColor Yellow

$svcBackend = "BiliMind-Backend"

# 如果服务已存在，先停止并删除
$existing = Get-Service -Name $svcBackend -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "  Service already exists, removing ..."
    & $NSSM stop $svcBackend 2>$null
    & $NSSM remove $svcBackend confirm 2>$null
    Start-Sleep -Seconds 2
}

# 注册服务：使用 venv 中的 python 运行 uvicorn
& $NSSM install $svcBackend "$PROJECT_ROOT\.venv\Scripts\python.exe"
& $NSSM set $svcBackend AppParameters "-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --no-access-log"
& $NSSM set $svcBackend AppDirectory "$PROJECT_ROOT"
& $NSSM set $svcBackend Description "BiliMind FastAPI Backend Service"
& $NSSM set $svcBackend Start SERVICE_AUTO_START

# 日志配置
& $NSSM set $svcBackend AppStdout "$LOG_DIR\backend-stdout.log"
& $NSSM set $svcBackend AppStderr "$LOG_DIR\backend-stderr.log"
& $NSSM set $svcBackend AppStdoutCreationDisposition 4
& $NSSM set $svcBackend AppStderrCreationDisposition 4
& $NSSM set $svcBackend AppRotateFiles 1
& $NSSM set $svcBackend AppRotateBytes 10485760

# 失败重启策略：失败后 10 秒自动重启
& $NSSM set $svcBackend AppExit Default Restart
& $NSSM set $svcBackend AppRestartDelay 10000

Write-Host "  [OK] $svcBackend installed" -ForegroundColor Green

# ============================================================
# 服务 2：BiliMind-Frontend (Next.js)
# ============================================================
Write-Host "[2/3] Installing BiliMind-Frontend service ..." -ForegroundColor Yellow

$svcFrontend = "BiliMind-Frontend"

$existing = Get-Service -Name $svcFrontend -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "  Service already exists, removing ..."
    & $NSSM stop $svcFrontend 2>$null
    & $NSSM remove $svcFrontend confirm 2>$null
    Start-Sleep -Seconds 2
}

# 找到 npx 的完整路径
$npxPath = (Get-Command npx -ErrorAction SilentlyContinue).Source
if (-not $npxPath) {
    # 尝试常见路径
    $npxPath = "C:\Program Files\nodejs\npx.cmd"
}

# 注册服务
& $NSSM install $svcFrontend "$npxPath"
& $NSSM set $svcFrontend AppParameters "next start --port 3000 --hostname 127.0.0.1"
& $NSSM set $svcFrontend AppDirectory "$PROJECT_ROOT\frontend"
& $NSSM set $svcFrontend Description "BiliMind Next.js Frontend Service"
& $NSSM set $svcFrontend Start SERVICE_AUTO_START

# 环境变量
& $NSSM set $svcFrontend AppEnvironmentExtra "HOSTNAME=127.0.0.1" "PORT=3000"

# 日志配置
& $NSSM set $svcFrontend AppStdout "$LOG_DIR\frontend-stdout.log"
& $NSSM set $svcFrontend AppStderr "$LOG_DIR\frontend-stderr.log"
& $NSSM set $svcFrontend AppStdoutCreationDisposition 4
& $NSSM set $svcFrontend AppStderrCreationDisposition 4
& $NSSM set $svcFrontend AppRotateFiles 1
& $NSSM set $svcFrontend AppRotateBytes 10485760

# 失败重启策略
& $NSSM set $svcFrontend AppExit Default Restart
& $NSSM set $svcFrontend AppRestartDelay 10000

Write-Host "  [OK] $svcFrontend installed" -ForegroundColor Green

# ============================================================
# 服务 3：Caddy (反向代理)
# ============================================================
Write-Host "[3/3] Installing Caddy service ..." -ForegroundColor Yellow

$svcCaddy = "BiliMind-Caddy"

$existing = Get-Service -Name $svcCaddy -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "  Service already exists, removing ..."
    & $NSSM stop $svcCaddy 2>$null
    & $NSSM remove $svcCaddy confirm 2>$null
    Start-Sleep -Seconds 2
}

& $NSSM install $svcCaddy "$CADDY"
& $NSSM set $svcCaddy AppParameters "run --config C:\BiliMind\Caddyfile"
& $NSSM set $svcCaddy AppDirectory "$PROJECT_ROOT"
& $NSSM set $svcCaddy Description "BiliMind Caddy Reverse Proxy"
& $NSSM set $svcCaddy Start SERVICE_AUTO_START

# 日志
& $NSSM set $svcCaddy AppStdout "$LOG_DIR\caddy-stdout.log"
& $NSSM set $svcCaddy AppStderr "$LOG_DIR\caddy-stderr.log"
& $NSSM set $svcCaddy AppStdoutCreationDisposition 4
& $NSSM set $svcCaddy AppStderrCreationDisposition 4
& $NSSM set $svcCaddy AppRotateFiles 1
& $NSSM set $svcCaddy AppRotateBytes 10485760

# 失败重启
& $NSSM set $svcCaddy AppExit Default Restart
& $NSSM set $svcCaddy AppRestartDelay 5000

Write-Host "  [OK] $svcCaddy installed" -ForegroundColor Green

# ============================================================
# 启动所有服务
# ============================================================
Write-Host ""
Write-Host "Starting all services ..." -ForegroundColor Yellow

# 启动顺序：后端先，前端次，Caddy 最后
Start-Service $svcBackend
Write-Host "  [OK] $svcBackend started" -ForegroundColor Green
Start-Sleep -Seconds 3

Start-Service $svcFrontend
Write-Host "  [OK] $svcFrontend started" -ForegroundColor Green
Start-Sleep -Seconds 3

Start-Service $svcCaddy
Write-Host "  [OK] $svcCaddy started" -ForegroundColor Green

# ============================================================
# 验证
# ============================================================
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  All services installed and started!"
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Service status:" -ForegroundColor Yellow

Get-Service -Name "BiliMind-*" | Format-Table Name, Status, StartType -AutoSize

Write-Host ""
Write-Host "Verification:" -ForegroundColor Yellow
Write-Host "  1. Backend:  http://127.0.0.1:8000/docs" -ForegroundColor White
Write-Host "  2. Frontend: http://127.0.0.1:3000" -ForegroundColor White
Write-Host "  3. Public:   http://127.0.0.1 (via Caddy)" -ForegroundColor White
Write-Host ""
Write-Host "Manage services:" -ForegroundColor Yellow
Write-Host "  Restart:  Restart-Service BiliMind-Backend" -ForegroundColor Gray
Write-Host "  Stop:     Stop-Service BiliMind-Frontend" -ForegroundColor Gray
Write-Host "  Logs:     Get-Content C:\BiliMind\logs\backend-stderr.log -Tail 50" -ForegroundColor Gray
Write-Host "  Status:   Get-Service BiliMind-*" -ForegroundColor Gray
Write-Host ""
