@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PYTHONPATH=%~dp0..
set PYTHONIOENCODING=utf-8

if not exist "%~dp0..\python\python.exe" (
    echo [错误] 未找到嵌入式 Python，请先运行 setup.bat 初始化环境。
    pause
    exit /b 1
)

echo ==========================================
echo Linux.do 订阅器 - 完整模式（Web + 自动抓取）
echo ==========================================
echo 访问地址: http://127.0.0.1:5000
echo 抓取间隔: 详见 config.yaml
echo 按 Ctrl+C 停止服务
echo.
"%~dp0..\python\python.exe" "%~dp0..\main.py"

echo.
pause
