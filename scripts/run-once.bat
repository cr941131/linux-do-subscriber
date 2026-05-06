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
echo Linux.do 订阅器 - 单次抓取（交互式回填）
echo ==========================================
echo.
"%~dp0..\python\python.exe" "%~dp0..\main.py" --once

echo.
pause
