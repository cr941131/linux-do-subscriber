# Linux.do 订阅器 - 嵌入式 Python 环境初始化脚本
# 下载并配置 Windows Embeddable Python，无需系统安装 Python 即可运行

$ErrorActionPreference = "Stop"

# 配置：可修改为其他稳定版本
$PythonVersion = "3.11.9"
$PythonZip = "python-$PythonVersion-embed-amd64.zip"
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/$PythonZip"
$ProjectRoot = $PSScriptRoot
$PythonDir = Join-Path $ProjectRoot "python"

function Write-Info($msg) {
    Write-Host "[Setup] $msg" -ForegroundColor Cyan
}

function Write-Ok($msg) {
    Write-Host "[OK] $msg" -ForegroundColor Green
}

function Write-Warn($msg) {
    Write-Host "[WARN] $msg" -ForegroundColor Yellow
}

# 1. 检查是否已存在
if (Test-Path $PythonDir) {
    Write-Warn "python/ 目录已存在，跳过下载。如需重装请删除该目录后重试。"
} else {
    # 下载
    $TempZip = Join-Path $ProjectRoot $PythonZip
    Write-Info "正在下载 Embeddable Python $PythonVersion ..."
    try {
        Invoke-WebRequest -Uri $PythonUrl -OutFile $TempZip -UseBasicParsing
    } catch {
        Write-Host "下载失败: $_" -ForegroundColor Red
        Write-Host "请检查网络连接或手动下载 $PythonUrl 并解压到 python/ 目录" -ForegroundColor Red
        exit 1
    }

    # 解压
    Write-Info "解压到 python/ ..."
    Expand-Archive -Path $TempZip -DestinationPath $PythonDir -Force
    Remove-Item $TempZip
    Write-Ok "Python 解压完成"
}

# 2. 启用 pip 支持（修改 ._pth 文件）
$pthFile = Get-ChildItem $PythonDir -Filter "*._pth" | Select-Object -First 1
if (-not $pthFile) {
    Write-Host "错误：未找到 ._pth 文件，无法启用 pip。" -ForegroundColor Red
    exit 1
}

$pthPath = $pthFile.FullName
$pthContent = Get-Content $pthPath -Raw

if ($pthContent -match "^#import site\b" -or $pthContent -notmatch "^import site\b") {
    Write-Info "正在启用 pip 支持（修改 $($pthFile.Name)）..."
    $pthContent = $pthContent -replace "^#import site\b", "import site"
    # 确保 Lib\site-packages 在路径中
    if ($pthContent -notmatch "Lib\\site-packages") {
        $pthContent = $pthContent.TrimEnd() + "`r`nLib\site-packages`r`n"
    }
    Set-Content $pthPath $pthContent -NoNewline -Encoding ASCII
    Write-Ok "pip 支持已启用"
} else {
    Write-Ok "pip 支持已处于启用状态"
}

# 3. 安装 pip
$GetPipPath = Join-Path $PythonDir "get-pip.py"
if (-not (Test-Path $GetPipPath)) {
    Write-Info "下载 get-pip.py ..."
    try {
        Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPipPath -UseBasicParsing
    } catch {
        Write-Host "下载 get-pip.py 失败: $_" -ForegroundColor Red
        exit 1
    }
}

$PipExe = Join-Path $PythonDir "Scripts\pip.exe"
if (-not (Test-Path $PipExe)) {
    Write-Info "正在安装 pip ..."
    & "$PythonDir\python.exe" $GetPipPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host "pip 安装失败" -ForegroundColor Red
        exit 1
    }
    Write-Ok "pip 安装完成"
} else {
    Write-Ok "pip 已存在"
}

# 4. 安装项目依赖
Write-Info "正在安装项目依赖 ..."
& "$PythonDir\python.exe" -m pip install -r "$ProjectRoot\requirements.txt"
if ($LASTEXITCODE -ne 0) {
    Write-Host "依赖安装失败，请检查 requirements.txt 和网络" -ForegroundColor Red
    exit 1
}
Write-Ok "依赖安装完成"

# 5. 验证
Write-Info "验证环境 ..."
& "$PythonDir\python.exe" -c "import flask, requests, yaml; print('All imports OK')"
if ($LASTEXITCODE -eq 0) {
    Write-Ok "环境验证通过"
} else {
    Write-Warn "环境验证未完全通过，可能需要手动检查"
}

Write-Host ""
Write-Ok "嵌入式 Python 环境初始化完成！"
Write-Host ""
Write-Host "使用方法：" -ForegroundColor White
Write-Host "  双击 run-once.bat   - 交互式完整回填（首次推荐）" -ForegroundColor White
Write-Host "  双击 run-web.bat    - 仅启动 Web 浏览服务" -ForegroundColor White
Write-Host "  双击 run-full.bat   - 启动 Web + 后台自动抓取" -ForegroundColor White
Write-Host ""
