@echo off
chcp 65001 > nul
cd /d "%~dp0.."
echo ==========================================
echo Linux.do 订阅器 - 嵌入式环境初始化
echo ==========================================
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0setup-embed.ps1"
echo.
pause
