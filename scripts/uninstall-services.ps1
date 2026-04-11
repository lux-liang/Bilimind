# ============================================================
# BiliMind - 卸载 Windows 服务脚本
# ============================================================
#
# 用途：停止并卸载所有 BiliMind Windows 服务
# 执行方式：以管理员身份运行 PowerShell：
#   powershell -ExecutionPolicy Bypass -File C:\BiliMind\scripts\uninstall-services.ps1
#
# 可安全重复执行。
# ============================================================

#Requires -RunAsAdministrator

$ErrorActionPreference = "Continue"

$NSSM = "C:\Tools\nssm\nssm.exe"

$services = @("BiliMind-Backend", "BiliMind-Frontend", "BiliMind-Caddy")

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  BiliMind - Uninstall Windows Services"
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

foreach ($svc in $services) {
    $existing = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "Stopping $svc ..." -ForegroundColor Yellow
        Stop-Service -Name $svc -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2

        if (Test-Path $NSSM) {
            Write-Host "Removing $svc via NSSM ..." -ForegroundColor Yellow
            & $NSSM remove $svc confirm 2>$null
        } else {
            # NSSM 不在了，用 sc.exe 删除
            Write-Host "Removing $svc via sc.exe ..." -ForegroundColor Yellow
            sc.exe delete $svc 2>$null
        }

        Write-Host "  [OK] $svc removed" -ForegroundColor Green
    } else {
        Write-Host "  [SKIP] $svc not found (already removed)" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "All BiliMind services have been uninstalled." -ForegroundColor Cyan
Write-Host "Project files and data in C:\BiliMind are NOT deleted." -ForegroundColor Yellow
Write-Host ""
