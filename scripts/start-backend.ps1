# ============================================================
# BiliMind - 后端启动脚本 (FastAPI + uvicorn)
# ============================================================
#
# 用途：在 C:\BiliMind 目录下启动 FastAPI 后端
# 调用方式：
#   - 手动测试：powershell -File C:\BiliMind\scripts\start-backend.ps1
#   - NSSM 服务：由 install-services.ps1 注册
#
# 监听地址：127.0.0.1:8000（仅本机，不对外暴露）
# ============================================================

$ErrorActionPreference = "Stop"

# --- 路径定义 ---
$PROJECT_ROOT = "C:\BiliMind"
$VENV_PYTHON  = "$PROJECT_ROOT\.venv\Scripts\python.exe"
$LOG_DIR      = "$PROJECT_ROOT\logs"
$LOG_FILE     = "$LOG_DIR\backend.log"

# --- 切换到项目根目录（确保相对路径 ./data/ 等正确） ---
Set-Location $PROJECT_ROOT

# --- 检查虚拟环境 ---
if (-not (Test-Path $VENV_PYTHON)) {
    Write-Error "[BiliMind-Backend] Python venv not found at $VENV_PYTHON"
    Write-Error "[BiliMind-Backend] Please run deploy.ps1 first."
    exit 1
}

# --- 确保目录存在 ---
New-Item -ItemType Directory -Force -Path "$PROJECT_ROOT\data" | Out-Null
New-Item -ItemType Directory -Force -Path "$PROJECT_ROOT\data\chroma_db" | Out-Null
New-Item -ItemType Directory -Force -Path "$LOG_DIR" | Out-Null

# --- 检查 .env ---
if (-not (Test-Path "$PROJECT_ROOT\.env")) {
    Write-Warning "[BiliMind-Backend] .env file not found! System will start with defaults."
    Write-Warning "[BiliMind-Backend] AI features will NOT work without API keys."
}

# --- 启动 FastAPI ---
Write-Host "[BiliMind-Backend] Starting FastAPI on 127.0.0.1:8000 ..."
Write-Host "[BiliMind-Backend] Log file: $LOG_FILE"

# 使用 venv 中的 python 直接运行 uvicorn
# --proxy-headers: 让 FastAPI 信任反向代理传递的 X-Forwarded-* 头
# --no-access-log: 减少日志噪音（Caddy 已记录访问日志）
& $VENV_PYTHON -m uvicorn app.main:app `
    --host 127.0.0.1 `
    --port 8000 `
    --proxy-headers `
    --no-access-log `
    2>&1 | Tee-Object -FilePath $LOG_FILE -Append
