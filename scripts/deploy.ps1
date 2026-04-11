# ============================================================
# BiliMind - 一键部署准备脚本
# ============================================================
#
# 用途：在 Windows Server 上完成 BiliMind 的部署准备
# 前置条件：Git / Node.js 20+ / Python 3.10+ 已安装
# 执行方式：以管理员身份运行 PowerShell，执行：
#   powershell -ExecutionPolicy Bypass -File C:\BiliMind\scripts\deploy.ps1
#
# 本脚本不启动服务，只做环境准备。
# ============================================================

$ErrorActionPreference = "Continue"

$PROJECT_ROOT = "C:\BiliMind"
$FRONTEND_DIR = "$PROJECT_ROOT\frontend"
$VENV_DIR     = "$PROJECT_ROOT\.venv"
$DATA_DIR     = "$PROJECT_ROOT\data"
$LOG_DIR      = "$PROJECT_ROOT\logs"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  BiliMind Deployment Preparation"
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================
# 步骤 1：检查必要软件
# ============================================================
Write-Host "[1/8] Checking prerequisites ..." -ForegroundColor Yellow

$allOk = $true

# Git
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) {
    Write-Host "  [OK] Git: $($git.Version)" -ForegroundColor Green
} else {
    Write-Host "  [MISSING] Git not found. Install: winget install Git.Git" -ForegroundColor Red
    $allOk = $false
}

# Node.js
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    $nodeVer = (node --version 2>$null)
    Write-Host "  [OK] Node.js: $nodeVer" -ForegroundColor Green
    # 检查版本 >= 20
    $major = [int]($nodeVer -replace 'v(\d+)\..*', '$1')
    if ($major -lt 20) {
        Write-Host "  [WARNING] Node.js >= 20 required. Current: $nodeVer" -ForegroundColor Red
        Write-Host "  Install: winget install OpenJS.NodeJS.LTS" -ForegroundColor Red
        $allOk = $false
    }
} else {
    Write-Host "  [MISSING] Node.js not found. Install: winget install OpenJS.NodeJS.LTS" -ForegroundColor Red
    $allOk = $false
}

# Python
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    $pyVer = (python --version 2>$null)
    Write-Host "  [OK] Python: $pyVer" -ForegroundColor Green
} else {
    Write-Host "  [MISSING] Python not found. Install: winget install Python.Python.3.12" -ForegroundColor Red
    $allOk = $false
}

# ffmpeg (可选)
$ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ff) {
    Write-Host "  [OK] ffmpeg: found" -ForegroundColor Green
} else {
    Write-Host "  [OPTIONAL] ffmpeg not found. ASR local fallback will be disabled." -ForegroundColor Yellow
    Write-Host "  Install: winget install Gyan.FFmpeg" -ForegroundColor Yellow
}

if (-not $allOk) {
    Write-Host ""
    Write-Host "[ABORT] Please install missing prerequisites and re-run." -ForegroundColor Red
    exit 1
}

# ============================================================
# 步骤 2：检查项目目录
# ============================================================
Write-Host ""
Write-Host "[2/8] Checking project directory ..." -ForegroundColor Yellow

if (-not (Test-Path "$PROJECT_ROOT\app\main.py")) {
    Write-Host "  [ERROR] Project not found at $PROJECT_ROOT" -ForegroundColor Red
    Write-Host "  Please clone the project first:" -ForegroundColor Red
    Write-Host "    git clone https://github.com/lux-liang/Bilimind.git C:\BiliMind" -ForegroundColor White
    exit 1
}
Write-Host "  [OK] Project found at $PROJECT_ROOT" -ForegroundColor Green

# ============================================================
# 步骤 3：创建必要目录
# ============================================================
Write-Host ""
Write-Host "[3/8] Creating directories ..." -ForegroundColor Yellow

$dirs = @($DATA_DIR, "$DATA_DIR\chroma_db", "$DATA_DIR\asr_tmp", $LOG_DIR, "$PROJECT_ROOT\scripts")
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
    Write-Host "  [OK] $d" -ForegroundColor Green
}

# ============================================================
# 步骤 4：创建 Python 虚拟环境
# ============================================================
Write-Host ""
Write-Host "[4/8] Setting up Python virtual environment ..." -ForegroundColor Yellow

if (Test-Path "$VENV_DIR\Scripts\python.exe") {
    Write-Host "  [OK] venv already exists at $VENV_DIR" -ForegroundColor Green
} else {
    Write-Host "  Creating venv ..."
    python -m venv $VENV_DIR
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERROR] Failed to create venv" -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] venv created" -ForegroundColor Green
}

# ============================================================
# 步骤 5：安装 Python 依赖
# ============================================================
Write-Host ""
Write-Host "[5/8] Installing Python dependencies ..." -ForegroundColor Yellow

& "$VENV_DIR\Scripts\pip.exe" install -r "$PROJECT_ROOT\requirements.txt" --quiet 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERROR] pip install failed. Check network and retry." -ForegroundColor Red
    Write-Host "  You can retry manually:" -ForegroundColor Yellow
    Write-Host "    $VENV_DIR\Scripts\pip.exe install -r $PROJECT_ROOT\requirements.txt" -ForegroundColor White
    exit 1
}
Write-Host "  [OK] Python dependencies installed" -ForegroundColor Green

# ============================================================
# 步骤 6：安装前端依赖
# ============================================================
Write-Host ""
Write-Host "[6/8] Installing frontend dependencies ..." -ForegroundColor Yellow

Set-Location $FRONTEND_DIR
npm install --omit=dev 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERROR] npm install failed" -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] npm dependencies installed" -ForegroundColor Green

# ============================================================
# 步骤 7：构建前端
# ============================================================
Write-Host ""
Write-Host "[7/8] Building frontend (npm run build) ..." -ForegroundColor Yellow

npm run build 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERROR] npm run build failed" -ForegroundColor Red
    Write-Host "  Check the error above and fix before proceeding." -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] Frontend built successfully" -ForegroundColor Green

# ============================================================
# 步骤 8：检查 .env
# ============================================================
Write-Host ""
Write-Host "[8/8] Checking .env configuration ..." -ForegroundColor Yellow

Set-Location $PROJECT_ROOT

if (Test-Path "$PROJECT_ROOT\.env") {
    Write-Host "  [OK] .env file exists" -ForegroundColor Green

    # 检查 DEBUG 设置
    $envContent = Get-Content "$PROJECT_ROOT\.env" -Raw
    if ($envContent -match "DEBUG\s*=\s*true") {
        Write-Host "  [WARNING] DEBUG=true detected in .env" -ForegroundColor Red
        Write-Host "  For production, change to: DEBUG=false" -ForegroundColor Red
        Write-Host ""
        $confirm = Read-Host "  Auto-fix DEBUG=false now? (y/n)"
        if ($confirm -eq "y") {
            (Get-Content "$PROJECT_ROOT\.env") -replace 'DEBUG\s*=\s*true', 'DEBUG=false' |
                Set-Content "$PROJECT_ROOT\.env"
            Write-Host "  [OK] DEBUG set to false" -ForegroundColor Green
        }
    }

    # 检查 API Key
    if ($envContent -match "DASHSCOPE_API_KEY\s*=\s*sk-") {
        Write-Host "  [OK] API key configured" -ForegroundColor Green
    } else {
        Write-Host "  [WARNING] No valid API key found in .env" -ForegroundColor Yellow
        Write-Host "  AI features (knowledge extraction, Q&A) will NOT work." -ForegroundColor Yellow
        Write-Host "  Knowledge tree browsing will still work if data exists." -ForegroundColor Yellow
    }
} else {
    Write-Host "  [WARNING] .env not found! Copying from .env.example ..." -ForegroundColor Yellow
    Copy-Item "$PROJECT_ROOT\.env.example" "$PROJECT_ROOT\.env"
    Write-Host "  [ACTION REQUIRED] Please edit C:\BiliMind\.env and configure:" -ForegroundColor Red
    Write-Host "    1. DASHSCOPE_API_KEY (or OPENAI_API_KEY)" -ForegroundColor White
    Write-Host "    2. Set DEBUG=false" -ForegroundColor White
    Write-Host "    3. Set OPENAI_BASE_URL if using DeepSeek" -ForegroundColor White
}

# ============================================================
# 完成
# ============================================================
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Deployment preparation complete!"
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps - manual testing:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  1. Test backend:" -ForegroundColor White
Write-Host "     cd C:\BiliMind" -ForegroundColor Gray
Write-Host "     .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000" -ForegroundColor Gray
Write-Host "     Open: http://127.0.0.1:8000/docs" -ForegroundColor Gray
Write-Host ""
Write-Host "  2. Test frontend (new terminal):" -ForegroundColor White
Write-Host "     cd C:\BiliMind\frontend" -ForegroundColor Gray
Write-Host "     npx next start --port 3000 --hostname 127.0.0.1" -ForegroundColor Gray
Write-Host "     Open: http://127.0.0.1:3000" -ForegroundColor Gray
Write-Host ""
Write-Host "  3. Test Caddy (new terminal, requires admin):" -ForegroundColor White
Write-Host "     C:\Tools\Caddy\caddy.exe run --config C:\BiliMind\Caddyfile" -ForegroundColor Gray
Write-Host "     Open: http://127.0.0.1" -ForegroundColor Gray
Write-Host ""
Write-Host "  4. After all tests pass, register services:" -ForegroundColor White
Write-Host "     powershell -ExecutionPolicy Bypass -File C:\BiliMind\scripts\install-services.ps1" -ForegroundColor Gray
Write-Host ""
