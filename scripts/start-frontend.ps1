# ============================================================
# BiliMind - 前端启动脚本 (Next.js production)
# ============================================================
#
# 用途：在 C:\BiliMind\frontend 目录下启动 Next.js 生产服务
# 前置条件：已执行 npm run build
# 调用方式：
#   - 手动测试：powershell -File C:\BiliMind\scripts\start-frontend.ps1
#   - NSSM 服务：由 install-services.ps1 注册
#
# 监听地址：127.0.0.1:3000（仅本机，Caddy 反代后对外暴露）
# ============================================================

$ErrorActionPreference = "Stop"

# --- 路径定义 ---
$PROJECT_ROOT  = "C:\BiliMind"
$FRONTEND_DIR  = "$PROJECT_ROOT\frontend"
$LOG_DIR       = "$PROJECT_ROOT\logs"
$LOG_FILE      = "$LOG_DIR\frontend.log"

# --- 切换到前端目录 ---
Set-Location $FRONTEND_DIR

# --- 检查 node_modules ---
if (-not (Test-Path "$FRONTEND_DIR\node_modules")) {
    Write-Error "[BiliMind-Frontend] node_modules not found."
    Write-Error "[BiliMind-Frontend] Please run deploy.ps1 first."
    exit 1
}

# --- 检查 .next 构建产物 ---
if (-not (Test-Path "$FRONTEND_DIR\.next")) {
    Write-Error "[BiliMind-Frontend] .next build output not found."
    Write-Error "[BiliMind-Frontend] Please run: cd $FRONTEND_DIR && npm run build"
    exit 1
}

# --- 确保日志目录存在 ---
New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

# --- 设置环境变量 ---
# HOSTNAME: 限制 Next.js 只监听本机，不直接暴露给公网
# PORT: 明确指定端口
$env:HOSTNAME = "127.0.0.1"
$env:PORT = "3000"

# --- 启动 Next.js 生产服务 ---
Write-Host "[BiliMind-Frontend] Starting Next.js on 127.0.0.1:3000 ..."
Write-Host "[BiliMind-Frontend] Log file: $LOG_FILE"

npx next start --port 3000 --hostname 127.0.0.1 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
