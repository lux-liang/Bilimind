# BiliMind Windows Server 部署指南

本文档面向腾讯云轻量应用服务器（Windows Server），指导你从零完成 BiliMind 的公网部署。

---

## 目录

1. [服务器环境准备](#1-服务器环境准备)
2. [获取代码](#2-获取代码)
3. [下载工具软件](#3-下载工具软件)
4. [执行部署脚本](#4-执行部署脚本)
5. [配置环境变量](#5-配置环境变量)
6. [手动测试](#6-手动测试)
7. [配置防火墙](#7-配置防火墙)
8. [注册系统服务](#8-注册系统服务)
9. [公网验证](#9-公网验证)
10. [日常运维](#10-日常运维)
11. [后续：域名与 HTTPS](#11-后续域名与-https)
12. [故障排查](#12-故障排查)

---

## 1. 服务器环境准备

### 1.1 连接服务器

通过远程桌面（RDP）连接腾讯云 Windows Server：

```
mstsc /v:<公网IP>:3389
```

用户名：`Administrator`，密码：腾讯云控制台设置的密码。

### 1.2 安装必要软件

以**管理员身份**打开 PowerShell，执行：

```powershell
# Git
winget install Git.Git

# Node.js 20 LTS
winget install OpenJS.NodeJS.LTS

# Python 3.12
winget install Python.Python.3.12

# ffmpeg（可选，ASR 本地转写需要）
winget install Gyan.FFmpeg
```

安装完成后**重启 PowerShell**（或注销重新登录），确保 PATH 生效。

验证：

```powershell
git --version
node --version      # 应 >= v20
python --version    # 应 >= 3.10
ffmpeg -version     # 可选
```

如果 `winget` 不可用（部分 Windows Server 未预装），请手动下载安装：
- Git: https://git-scm.com/download/win
- Node.js: https://nodejs.org/ （选 LTS 版本）
- Python: https://www.python.org/downloads/ （安装时勾选 "Add to PATH"）

---

## 2. 获取代码

```powershell
git clone https://github.com/lux-liang/Bilimind.git C:\BiliMind
```

如果 GitHub 访问慢，可以在本地打包后通过 SCP/远程桌面复制到服务器。

---

## 3. 下载工具软件

### 3.1 Caddy（反向代理）

1. 访问 https://caddyserver.com/download （选 Windows amd64）
2. 下载 `caddy_windows_amd64.exe`
3. 创建目录并放置：

```powershell
New-Item -ItemType Directory -Force -Path "C:\Tools\Caddy"
# 将下载的 exe 重命名并移动到：
# C:\Tools\Caddy\caddy.exe
```

验证：

```powershell
C:\Tools\Caddy\caddy.exe version
```

### 3.2 NSSM（服务管理）

1. 访问 https://nssm.cc/download
2. 下载最新版 zip
3. 解压，将 `win64/nssm.exe` 放到：

```powershell
New-Item -ItemType Directory -Force -Path "C:\Tools\nssm"
# 将 nssm.exe 放到：
# C:\Tools\nssm\nssm.exe
```

验证：

```powershell
C:\Tools\nssm\nssm.exe version
```

---

## 4. 执行部署脚本

以**管理员身份**打开 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File C:\BiliMind\scripts\deploy.ps1
```

脚本会自动完成：
- 检查 Git / Node / Python 是否就绪
- 创建 Python 虚拟环境
- 安装 Python 依赖
- 安装前端依赖
- 构建前端（`npm run build`）
- 创建 data / logs 目录
- 检查 .env 配置

> 整个过程约 3-10 分钟，取决于网速。

---

## 5. 配置环境变量

编辑 `C:\BiliMind\.env`：

```powershell
notepad C:\BiliMind\.env
```

**必须检查的项目：**

```ini
# 必须：至少配置一个 API Key（DeepSeek 或 DashScope）
DASHSCOPE_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://api.deepseek.com/v1   # 如果用 DeepSeek

# 必须：生产环境关闭调试
DEBUG=false
```

**功能降级说明：**

| 配置状态 | 可用功能 | 不可用功能 |
|----------|----------|------------|
| 有 API Key | 全部功能 | — |
| 无 API Key | 知识树浏览（已有数据时）、搜索、登录 | 知识抽取、问答、学习路径生成 |

---

## 6. 手动测试

在注册服务之前，先手动测试每个组件。

### 6.1 测试后端

打开 PowerShell 终端 1：

```powershell
cd C:\BiliMind
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开浏览器访问：http://127.0.0.1:8000/docs

- 看到 Swagger 文档页面 = 后端正常
- `Ctrl+C` 停止

### 6.2 测试前端

打开 PowerShell 终端 2：

```powershell
cd C:\BiliMind\frontend
npx next start --port 3000 --hostname 127.0.0.1
```

打开浏览器访问：http://127.0.0.1:3000

- 看到 BiliMind 首页 = 前端正常
- `Ctrl+C` 停止

### 6.3 测试 Caddy

先确保后端和前端都在运行（重新启动上面两个终端），然后打开 PowerShell 终端 3：

```powershell
C:\Tools\Caddy\caddy.exe run --config C:\BiliMind\Caddyfile
```

打开浏览器访问：http://127.0.0.1

- 看到 BiliMind 首页（通过 Caddy 代理）= 反向代理正常
- `Ctrl+C` 停止所有三个终端

---

## 7. 配置防火墙

### 7.1 腾讯云控制台防火墙

登录腾讯云控制台 → 轻量应用服务器 → 防火墙 → 添加规则：

| 协议 | 端口 | 策略 | 备注 |
|------|------|------|------|
| TCP | 80 | 允许 | HTTP 公网访问 |
| TCP | 443 | 允许 | HTTPS（后续用） |
| TCP | 3389 | 允许 | 远程桌面（默认已开） |

**不要开放 3000 和 8000**。

### 7.2 Windows Defender 防火墙

以管理员身份运行 PowerShell：

```powershell
# 允许 Caddy 监听 80 端口
New-NetFirewallRule -DisplayName "BiliMind Caddy HTTP" `
    -Direction Inbound -Protocol TCP -LocalPort 80 `
    -Action Allow -Profile Any

# 验证规则已添加
Get-NetFirewallRule -DisplayName "BiliMind*" | Format-Table DisplayName, Enabled, Direction
```

---

## 8. 注册系统服务

手动测试全部通过后，注册为 Windows 服务（开机自启）：

```powershell
powershell -ExecutionPolicy Bypass -File C:\BiliMind\scripts\install-services.ps1
```

检查服务状态：

```powershell
Get-Service BiliMind-*
```

应看到三个服务都是 `Running` 状态：

```
Name                Status   StartType
----                ------   ---------
BiliMind-Backend    Running  Automatic
BiliMind-Frontend   Running  Automatic
BiliMind-Caddy      Running  Automatic
```

---

## 9. 公网验证

在你自己的电脑（不是服务器）上，打开浏览器访问：

```
http://<服务器公网IP>
```

### 验证清单

| # | 测试项 | 预期结果 | 状态 |
|---|--------|----------|------|
| 1 | 打开首页 | 看到 BiliMind landing page | |
| 2 | 静态资源 | 字体、图标、样式正常加载 | |
| 3 | 路由跳转 | 点击"知识树"等导航正常 | |
| 4 | 扫码登录 | 弹出二维码弹窗 | |
| 5 | 知识树页 | 三栏布局显示（可能无数据） | |
| 6 | 搜索页 | 搜索框和筛选 tab 显示正常 | |
| 7 | 刷新页面 | 任意页面 F5 刷新不 404 | |
| 8 | API 连通 | 知识树页能请求到后端（查看网络请求） | |

### 重启验证

在服务器上重启系统，等 2 分钟后再次访问 `http://<公网IP>`，确认服务自动恢复。

---

## 10. 日常运维

### 查看服务状态

```powershell
Get-Service BiliMind-*
```

### 重启单个服务

```powershell
Restart-Service BiliMind-Backend
Restart-Service BiliMind-Frontend
Restart-Service BiliMind-Caddy
```

### 重启全部服务

```powershell
Get-Service BiliMind-* | Restart-Service
```

### 查看日志

```powershell
# 后端日志（最后 50 行）
Get-Content C:\BiliMind\logs\backend-stderr.log -Tail 50

# 前端日志
Get-Content C:\BiliMind\logs\frontend-stderr.log -Tail 50

# Caddy 日志
Get-Content C:\BiliMind\logs\caddy-stderr.log -Tail 50

# 后端应用日志（loguru 写的）
Get-Content C:\BiliMind\logs\app.log -Tail 50

# 实时跟踪日志
Get-Content C:\BiliMind\logs\backend-stderr.log -Wait
```

### 更新代码后重新部署

```powershell
# 1. 停服务
Get-Service BiliMind-* | Stop-Service

# 2. 拉取最新代码
cd C:\BiliMind
git pull

# 3. 更新依赖（如有变化）
.\.venv\Scripts\pip.exe install -r requirements.txt
cd frontend && npm install && npm run build
cd ..

# 4. 重启服务
Get-Service BiliMind-* | Start-Service
```

### 卸载服务

```powershell
powershell -ExecutionPolicy Bypass -File C:\BiliMind\scripts\uninstall-services.ps1
```

---

## 11. 后续：域名与 HTTPS

当 IP 部署稳定后，可选添加域名和 HTTPS。

### 11.1 域名解析

1. 在域名注册商处添加 A 记录：
   - 主机记录：`@` 或 `bilimind`
   - 记录值：服务器公网 IP
   - TTL：600
2. 如果域名在腾讯云：控制台 → 云解析 DNS → 添加记录

### 11.2 修改 Caddy 配置

编辑 `C:\BiliMind\Caddyfile`，将 `:80` 改为域名：

```caddyfile
bilimind.your-domain.com {
    reverse_proxy localhost:3000 {
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
        flush_interval -1
    }

    log {
        output file C:\BiliMind\logs\caddy-access.log {
            roll_size 10mb
            roll_keep 5
        }
    }
}
```

Caddy 会**自动**：
- 申请 Let's Encrypt 证书
- 配置 HTTPS
- 设置 HTTP → HTTPS 跳转
- 自动续期证书

### 11.3 重载 Caddy

```powershell
C:\Tools\Caddy\caddy.exe reload --config C:\BiliMind\Caddyfile
```

或重启服务：

```powershell
Restart-Service BiliMind-Caddy
```

### 11.4 确保 443 端口开放

腾讯云控制台和 Windows 防火墙都要放行 443：

```powershell
New-NetFirewallRule -DisplayName "BiliMind Caddy HTTPS" `
    -Direction Inbound -Protocol TCP -LocalPort 443 `
    -Action Allow -Profile Any
```

---

## 12. 故障排查

### 问题：127.0.0.1:8000 打不开

```powershell
# 检查后端服务状态
Get-Service BiliMind-Backend

# 查看后端错误日志
Get-Content C:\BiliMind\logs\backend-stderr.log -Tail 30

# 常见原因：
# - .env 文件不存在或格式错误
# - Python 依赖缺失 → 重新 pip install -r requirements.txt
# - 端口被占用 → netstat -ano | findstr :8000
```

### 问题：127.0.0.1:3000 打不开

```powershell
# 检查前端服务状态
Get-Service BiliMind-Frontend

# 查看前端错误日志
Get-Content C:\BiliMind\logs\frontend-stderr.log -Tail 30

# 常见原因：
# - npm run build 未执行或失败 → 重新构建
# - node_modules 缺失 → cd frontend && npm install
# - Node.js 版本 < 20 → node --version
```

### 问题：80 端口公网打不开

```powershell
# 1. 检查 Caddy 是否运行
Get-Service BiliMind-Caddy

# 2. 检查 Caddy 日志
Get-Content C:\BiliMind\logs\caddy-stderr.log -Tail 20

# 3. 检查 80 端口是否被监听
netstat -ano | findstr :80

# 4. 检查 Windows 防火墙
Get-NetFirewallRule -DisplayName "BiliMind*"

# 5. 检查腾讯云防火墙
# → 登录腾讯云控制台 → 轻量应用服务器 → 防火墙 → 确认 80 端口已放行

# 6. 80 端口被其他程序占用（如 IIS）
# 停止 IIS：
Stop-Service W3SVC -ErrorAction SilentlyContinue
Set-Service W3SVC -StartupType Disabled -ErrorAction SilentlyContinue
```

### 问题：Caddy 启动失败

```powershell
# 手动运行查看详细错误
C:\Tools\Caddy\caddy.exe run --config C:\BiliMind\Caddyfile

# 常见原因：
# - 80 端口被 IIS 或其他程序占用
# - Caddyfile 语法错误
# - caddy.exe 路径不正确
```

### 问题：Next.js build 失败

```powershell
cd C:\BiliMind\frontend

# 清理重新构建
Remove-Item -Recurse -Force .next -ErrorAction SilentlyContinue
npm run build

# 常见原因：
# - TypeScript 类型错误（查看 build 输出）
# - node_modules 损坏 → 删除 node_modules 重新 npm install
# - Node.js 版本不够 → 升级到 20+
```

### 问题：Python 依赖安装失败

```powershell
# 使用镜像源
C:\BiliMind\.venv\Scripts\pip.exe install -r C:\BiliMind\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 常见原因：
# - 网络问题 → 使用清华/阿里镜像
# - Visual C++ Build Tools 缺失（部分包需要编译）
#   → 安装 https://visualstudio.microsoft.com/visual-cpp-build-tools/
```

### 问题：sqlite database is locked

```powershell
# 检查是否有多个后端进程
Get-Process python | Format-Table Id, ProcessName, Path

# 确保只有一个后端实例在运行
# 如果有多个，杀掉多余的：
# Stop-Process -Id <进程ID>

# 当前部署方案（单进程 uvicorn + WAL 模式 + 30s timeout）
# 正常情况下不会出现此问题
```

### 问题：没有 DashScope / DeepSeek API Key

系统可以正常启动和访问，但以下功能不可用：
- 知识抽取（无法从视频构建知识库）
- 问答功能
- 学习路径自动生成

以下功能仍然可用（如果数据库中已有数据）：
- 知识树浏览
- 搜索
- 视频详情
- 节点详情
- 登录

---

## 附录：文件结构

```
C:\BiliMind\
├── app\                    # FastAPI 后端
├── frontend\               # Next.js 前端
│   └── .next\              # 构建产物
├── data\                   # 数据目录
│   ├── bilimind.db         # SQLite 数据库
│   ├── chroma_db\          # 向量数据库
│   └── graph.json          # 知识图谱
├── logs\                   # 所有日志
│   ├── app.log             # 后端应用日志
│   ├── backend-stderr.log  # 后端服务日志
│   ├── frontend-stderr.log # 前端服务日志
│   ├── caddy-stderr.log    # Caddy 服务日志
│   └── caddy-access.log    # Caddy 访问日志
├── scripts\                # 部署脚本
│   ├── deploy.ps1
│   ├── install-services.ps1
│   ├── uninstall-services.ps1
│   ├── start-backend.ps1
│   └── start-frontend.ps1
├── .env                    # 环境变量（不提交到 Git）
├── .env.example            # 环境变量模板
├── Caddyfile               # Caddy 反向代理配置
├── requirements.txt        # Python 依赖
└── DEPLOY_WINDOWS.md       # 本文档
```

## 附录：端口规划

| 端口 | 服务 | 监听地址 | 对外暴露 |
|------|------|----------|----------|
| 80 | Caddy | 0.0.0.0 | 是（公网入口） |
| 443 | Caddy（HTTPS 阶段） | 0.0.0.0 | 是 |
| 3000 | Next.js | 127.0.0.1 | 否 |
| 8000 | FastAPI | 127.0.0.1 | 否 |
| 3389 | 远程桌面 | 0.0.0.0 | 是（仅运维） |
